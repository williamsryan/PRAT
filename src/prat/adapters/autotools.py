"""Conservative adapter for conventional Autotools projects."""

from __future__ import annotations

from ..compilation import BuildSystem
from .base import ProjectAdapter


class AutotoolsAdapter(ProjectAdapter):
    """Configure, build, and require the standard `make check` suite."""

    @property
    def build_system(self) -> BuildSystem:
        return BuildSystem.AUTOTOOLS

    @property
    def coverage_tool(self) -> str:
        return "gcov"

    @property
    def source_directories(self) -> list[str]:
        return ["src", "lib"]

    def normalize_feature_name(self, raw_option: str) -> str:
        lowered = raw_option.lower()
        for prefix in ("enable-", "disable-"):
            if lowered.startswith(prefix):
                return lowered[len(prefix):]
        return lowered

    def get_compile_command(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True,
    ) -> list[str]:
        command = ["./configure", self.format_feature_flag(feature, enabled)]
        if with_coverage:
            command.extend(["CFLAGS=--coverage", "CXXFLAGS=--coverage"])
        return command

    def get_build_commands(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True,
    ) -> list[list[str]]:
        return [
            self.get_compile_command(feature, enabled, with_coverage),
            ["make", "-j"],
        ]

    def get_clean_command(self) -> list[str]:
        return ["make", "distclean"]

    def get_test_command(self) -> list[str] | None:
        return ["make", "check"]

    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        state = "enable" if enabled else "disable"
        return f"--{state}-{feature.lower()}"

    def validate_project(self) -> bool:
        return (self.project_path / "configure").exists()
