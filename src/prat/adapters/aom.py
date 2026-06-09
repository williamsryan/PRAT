"""
Adapter for AOM (libaom — AV1 codec reference implementation).

Project: https://aomedia.googlesource.com/aom
Build system: CMake
Features: CONFIG_AV1_ENCODER, CONFIG_AV1_DECODER, CONFIG_AV1_HIGHBITDEPTH, etc.
"""

from pathlib import Path
from typing import List, Optional

from .base import ProjectAdapter
from ..compilation import BuildSystem


class AomAdapter(ProjectAdapter):
    """Adapter for AOM (libaom)."""

    @property
    def build_system(self) -> BuildSystem:
        return BuildSystem.CMAKE

    @property
    def coverage_tool(self) -> str:
        return "gcov"

    @property
    def source_directories(self) -> List[str]:
        return ["aom", "aom_dsp", "av1"]

    def get_compile_command(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True,
    ) -> List[str]:
        flag_value = "1" if enabled else "0"
        cmd = [
            "cmake",
            "-B", "build",
            f"-D{feature}={flag_value}",
            "-DCMAKE_BUILD_TYPE=Debug",
            "-DENABLE_TESTS=0",
            "-DENABLE_DOCS=0",
        ]
        if with_coverage:
            cmd.extend([
                "-DCMAKE_C_FLAGS=--coverage -fprofile-arcs -ftest-coverage",
                "-DCMAKE_CXX_FLAGS=--coverage -fprofile-arcs -ftest-coverage",
            ])
        cmd_build = ["cmake", "--build", "build", "--parallel"]
        return cmd + ["&&"] + cmd_build

    def get_clean_command(self) -> List[str]:
        return ["rm", "-rf", "build"]

    def get_test_command(self) -> Optional[List[str]]:
        # AOM test suite is heavy; use the testdata runner if available
        return None

    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        return f"-D{feature}={'1' if enabled else '0'}"

    def validate_project(self) -> bool:
        return (
            (self.project_path / "CMakeLists.txt").exists()
            and (self.project_path / "av1").exists()
        )

    def get_execution_commands(self, feature: str, enabled: bool) -> List[List[str]]:
        # AOM provides aomenc/aomdec; encode a short sequence for coverage
        return [
            ["build/aomenc", "--help"],  # minimal execution to generate some coverage
        ]


"""
Known features for AOM (libaom):
  - CONFIG_AV1_ENCODER: AV1 encoder support
  - CONFIG_AV1_DECODER: AV1 decoder support
  - CONFIG_AV1_HIGHBITDEPTH: High bit-depth support
  - CONFIG_MULTITHREAD: Threading support
  - CONFIG_WEBM_IO: WebM container I/O
"""
