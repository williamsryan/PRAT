"""
Rust project adapter for PRAT.

Handles Cargo-based builds with --features flags. Coverage uses modern
*source-based* LLVM coverage via `cargo llvm-cov` on the stable toolchain
(the historical `-Zprofile` gcov path was removed from rustc). The resulting
lcov is converted to PRAT's gcov format by the coverage module.
"""


from __future__ import annotations

import toml  # type: ignore[import-untyped]

from ..compilation import BuildSystem
from .base import ProjectAdapter


class RustAdapter(ProjectAdapter):
    """
    Adapter for Rust projects using Cargo.

    Build system: Cargo
    Feature differential: every command spells out the exact active feature
      set using ``--no-default-features`` plus the preserved default features.
      This allows PRAT to disable a feature even when it belongs to Cargo's
      default set without accidentally dropping unrelated defaults.
    Coverage: `cargo llvm-cov` (stable, source-based) → lcov → gcov.
    """

    @property
    def build_system(self) -> BuildSystem:
        return BuildSystem.CARGO

    @property
    def coverage_tool(self) -> str:
        return "llvm-cov"

    @property
    def source_directories(self) -> list[str]:
        return ["src"]

    def get_compile_command(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True
    ) -> list[str]:
        """Validate the build with the target feature explicitly on or off."""
        cmd = ["cargo", "build", "--lib"]
        cmd.extend(self._feature_args({feature: enabled}))
        return cmd

    def get_llvm_cov_command(self, feature: str, enabled: bool, lcov_path: str) -> list[str]:
        """`cargo llvm-cov` command that builds, runs lib tests, and emits lcov.

        The exact default-preserving feature set is passed in both states.
        """
        cmd = ["cargo", "llvm-cov", "--lib"]
        cmd.extend(self._feature_args({feature: enabled}))
        cmd.extend(["--lcov", "--output-path", lcov_path])
        return cmd

    def get_llvm_cov_command_for_set(
        self,
        feature_states: dict[str, bool],
        lcov_path: str,
    ) -> list[str]:
        """`cargo llvm-cov` for an explicit feature set (Algorithm 1 baselines)."""
        cmd = ["cargo", "llvm-cov", "--lib"]
        cmd.extend(self._feature_args(feature_states))
        cmd.extend(["--lcov", "--output-path", lcov_path])
        return cmd

    def get_build_commands_for_set(
        self,
        feature_states: dict[str, bool],
        with_coverage: bool = True,
    ) -> list[list[str]]:
        """Cargo takes one comma-separated ``--features`` list, not one flag each.

        The base implementation would emit repeated ``--features`` arguments, so
        this collapses the enabled set into one exact, default-preserving list.
        """
        cmd = ["cargo", "build", "--lib"]
        cmd.extend(self._feature_args(feature_states))
        return [cmd]

    def _default_features(self) -> set[str]:
        """Read Cargo's default feature list from this package manifest."""
        try:
            manifest = toml.load(self.project_path / "Cargo.toml")
        except (OSError, toml.TomlDecodeError):
            return set()
        features = manifest.get("features", {})
        defaults = features.get("default", []) if isinstance(features, dict) else []
        return {
            str(feature).lower()
            for feature in defaults
            if isinstance(feature, str)
        }

    def _feature_args(self, feature_states: dict[str, bool]) -> list[str]:
        """Encode an exact feature set while preserving unrelated defaults."""
        normalized = {
            name.lower(): enabled for name, enabled in feature_states.items()
        }
        enabled = {
            name for name, state in normalized.items() if state
        }
        enabled.update(
            default
            for default in self._default_features()
            if normalized.get(default, True)
        )
        args = ["--no-default-features"]
        if enabled:
            args.extend(["--features", ",".join(sorted(enabled))])
        return args

    def get_clean_command(self) -> list[str]:
        """Remove all build + coverage artifacts (target/ incl. llvm-cov-target)."""
        return ["cargo", "clean"]

    def get_test_command(self) -> list[str] | None:
        return ["cargo", "test", "--lib"]

    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        state = "enabled" if enabled else "disabled"
        return f"{feature.lower()}={state}"

    def get_binary_path(self) -> str | None:
        target_dir = self.project_path / "target" / "debug"
        if target_dir.exists():
            return str(target_dir)
        return None

    def get_coverage_environment(self) -> dict[str, str]:
        # cargo-llvm-cov manages RUSTFLAGS/instrumentation itself; nothing extra.
        return {}

    def get_execution_commands(self, feature: str, enabled: bool) -> list[list[str]]:
        # Execution (test runs) is driven by `cargo llvm-cov` during coverage
        # generation, not here.
        return []

    def coverage_command_executes_tests(self) -> bool:
        return True

    def validate_project(self) -> bool:
        cargo_toml = self.project_path / "Cargo.toml"
        src_dir = self.project_path / "src"
        return cargo_toml.exists() and src_dir.exists()
