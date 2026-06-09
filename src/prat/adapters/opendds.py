"""
Adapter for OpenDDS (DDS implementation in C++).

Project: https://github.com/OpenDDS/OpenDDS
Build system: CMake (also supports MPC/ACE but CMake is modern path)
Features: SECURITY, CONTENT_SUBSCRIPTION, PERSISTENCE, etc.
"""

from pathlib import Path
from typing import List, Optional

from .base import ProjectAdapter
from ..compilation import BuildSystem


class OpenDDSAdapter(ProjectAdapter):
    """Adapter for OpenDDS."""

    @property
    def build_system(self) -> BuildSystem:
        return BuildSystem.CMAKE

    @property
    def coverage_tool(self) -> str:
        return "gcov"

    @property
    def source_directories(self) -> List[str]:
        return ["dds", "tools"]

    def get_compile_command(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True,
    ) -> List[str]:
        flag_value = "ON" if enabled else "OFF"
        cmd = [
            "cmake",
            "-B", "build",
            f"-DOPENDDS_{feature}={flag_value}",
            "-DCMAKE_BUILD_TYPE=Debug",
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
        return ["ctest", "--test-dir", "build", "--output-on-failure", "-j4"]

    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        return f"-DOPENDDS_{feature}={'ON' if enabled else 'OFF'}"

    def validate_project(self) -> bool:
        return (
            (self.project_path / "CMakeLists.txt").exists()
            and (self.project_path / "dds").exists()
        )

    def get_execution_commands(self, feature: str, enabled: bool) -> List[List[str]]:
        return [["ctest", "--test-dir", "build", "--output-on-failure", "-j4"]]


"""
Known features for OpenDDS:
  - SECURITY: DDS Security specification support (libssl)
  - CONTENT_SUBSCRIPTION: Content-filtered topics
  - PERSISTENCE: Durable subscriptions
  - BUILT_IN_TOPICS: Built-in topic support
"""
