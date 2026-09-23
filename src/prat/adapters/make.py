"""Conservative adapter for conventional Make projects."""

from __future__ import annotations

from ..compilation import BuildSystem
from .base import ProjectAdapter


class MakeAdapter(ProjectAdapter):
    """Build a Make project and require an executable test target."""

    @property
    def build_system(self) -> BuildSystem:
        return BuildSystem.MAKE

    @property
    def coverage_tool(self) -> str:
        return "gcov"

    @property
    def source_directories(self) -> list[str]:
        return ["src", "lib"]

    def normalize_feature_name(self, raw_option: str) -> str:
        upper = raw_option.upper()
        return upper[5:] if upper.startswith("WITH_") else upper

    def get_compile_command(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True,
    ) -> list[str]:
        command = ["make", "-j"]
        if with_coverage:
            command.append("CFLAGS=--coverage")
        command.append(self.format_feature_flag(feature, enabled))
        return command

    def get_clean_command(self) -> list[str]:
        return ["make", "clean"]

    def get_test_command(self) -> list[str] | None:
        return ["make", "test"]

    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        return f"WITH_{feature.upper()}={'yes' if enabled else 'no'}"

    def validate_project(self) -> bool:
        return (self.project_path / "Makefile").exists()
