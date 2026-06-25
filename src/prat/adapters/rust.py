"""
Rust project adapter for PRAT.

Handles Cargo-based builds with --features flags. Coverage uses modern
*source-based* LLVM coverage via `cargo llvm-cov` on the stable toolchain
(the historical `-Zprofile` gcov path was removed from rustc). The resulting
lcov is converted to PRAT's gcov format by the coverage module.
"""

from typing import Optional

from ..compilation import BuildSystem
from .base import ProjectAdapter


class RustAdapter(ProjectAdapter):
    """
    Adapter for Rust projects using Cargo.

    Build system: Cargo
    Feature differential: ENABLED = default features + `--features <feature>`;
      DISABLED = default features only (the feature omitted). We deliberately do
      NOT use `--no-default-features`, which would drop required defaults (e.g.
      quiche's vendored BoringSSL TLS backend) and break the build.
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
        """Validate the build compiles for this config (defaults preserved)."""
        cmd = ["cargo", "build", "--lib"]
        if enabled:
            cmd.extend(["--features", feature.lower()])
        return cmd

    def get_llvm_cov_command(self, feature: str, enabled: bool, lcov_path: str) -> list[str]:
        """`cargo llvm-cov` command that builds, runs lib tests, and emits lcov.

        ENABLED adds `--features <feature>`; DISABLED keeps default features only.
        """
        cmd = ["cargo", "llvm-cov", "--lib"]
        if enabled:
            cmd.extend(["--features", feature.lower()])
        cmd.extend(["--lcov", "--output-path", lcov_path])
        return cmd

    def get_clean_command(self) -> list[str]:
        """Remove all build + coverage artifacts (target/ incl. llvm-cov-target)."""
        return ["cargo", "clean"]

    def get_test_command(self) -> Optional[list[str]]:
        return ["cargo", "test", "--lib"]

    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        return f"--features {feature.lower()}" if enabled else "(default features)"

    def get_binary_path(self) -> Optional[str]:
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

    def validate_project(self) -> bool:
        cargo_toml = self.project_path / "Cargo.toml"
        src_dir = self.project_path / "src"
        return cargo_toml.exists() and src_dir.exists()
