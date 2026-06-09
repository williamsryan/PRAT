"""
Adapter for azure-uamqp-c (CMake-based AMQP library).

Project: https://github.com/Azure/azure-uamqp-c
Build system: CMake
Features: USE_WEBSOCKETS, USE_OPENSSL, USE_WOLFSSL, etc.
"""

from pathlib import Path
from typing import List, Optional

from .base import ProjectAdapter
from ..compilation import BuildSystem


class UamqpAdapter(ProjectAdapter):
    """Adapter for azure-uamqp-c."""

    @property
    def build_system(self) -> BuildSystem:
        return BuildSystem.CMAKE

    @property
    def coverage_tool(self) -> str:
        return "gcov"

    @property
    def source_directories(self) -> List[str]:
        return ["src", "deps"]

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
            f"-D{feature}={flag_value}",
            "-DCMAKE_BUILD_TYPE=Debug",
            "-Drun_unittests=OFF",
        ]
        if with_coverage:
            cmd.extend([
                "-DCMAKE_C_FLAGS=--coverage -fprofile-arcs -ftest-coverage",
                "-DCMAKE_CXX_FLAGS=--coverage -fprofile-arcs -ftest-coverage",
            ])
        # Build step
        cmd_build = ["cmake", "--build", "build", "--parallel"]
        return cmd + ["&&"] + cmd_build

    def get_clean_command(self) -> List[str]:
        return ["rm", "-rf", "build"]

    def get_test_command(self) -> Optional[List[str]]:
        return ["cmake", "--build", "build", "--target", "test"]

    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        return f"-D{feature}={'ON' if enabled else 'OFF'}"

    def validate_project(self) -> bool:
        return (
            (self.project_path / "CMakeLists.txt").exists()
            and (self.project_path / "src" / "amqp_management.c").exists()
        )

    def get_execution_commands(self, feature: str, enabled: bool) -> List[List[str]]:
        # azure-uamqp-c has unit tests via ctest
        return [["ctest", "--test-dir", "build", "--output-on-failure"]]
"""
Known features for azure-uamqp-c:
  - USE_WEBSOCKETS: WebSocket transport layer
  - USE_OPENSSL: OpenSSL TLS backend
  - USE_WOLFSSL: WolfSSL TLS backend
  - ENABLE_MOCKS: Test mock layer
"""
