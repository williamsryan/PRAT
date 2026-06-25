"""
Adapter for azure-uamqp-c (CMake-based AMQP library).

Project: https://github.com/Azure/azure-uamqp-c
Build system: CMake
Features: USE_WEBSOCKETS, USE_OPENSSL, USE_WOLFSSL, etc.
"""

from typing import Optional

from ..compilation import BuildSystem
from .base import ProjectAdapter


class UamqpAdapter(ProjectAdapter):
    """Adapter for azure-uamqp-c."""

    @property
    def build_system(self) -> BuildSystem:
        return BuildSystem.CMAKE

    @property
    def coverage_tool(self) -> str:
        return "gcov"

    @property
    def source_directories(self) -> list[str]:
        return ["src", "deps"]

    def get_compile_command(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True,
    ) -> list[str]:
        """Return ONLY the cmake configure command.

        The build step is returned separately by get_build_commands(). These
        must be separate argv lists because compile_with_adapter() runs each
        command with subprocess.run() WITHOUT a shell, so a literal "&&"
        token cannot chain them.
        """
        flag_value = "ON" if enabled else "OFF"
        cmd = [
            "cmake",
            "-B", "build",
            f"-D{feature}={flag_value}",
            "-DCMAKE_BUILD_TYPE=Debug",
            "-Drun_unittests=OFF",
            # The bundled samples (e.g. websockets_sample) link directly against
            # wsio symbols, so a use_wsio=OFF build fails at link time unless we
            # skip them. Samples are not part of the library under analysis.
            "-Dskip_samples=ON",
        ]
        if with_coverage:
            cmd.extend([
                "-DCMAKE_C_FLAGS=--coverage -fprofile-arcs -ftest-coverage",
                "-DCMAKE_CXX_FLAGS=--coverage -fprofile-arcs -ftest-coverage",
            ])
        return cmd

    def get_build_commands(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True,
    ) -> list[list[str]]:
        """Configure then build as two separate commands (no shell chaining)."""
        configure = self.get_compile_command(feature, enabled, with_coverage)
        build = ["cmake", "--build", "build", "--parallel"]
        return [configure, build]

    def get_clean_command(self) -> list[str]:
        return ["rm", "-rf", "build"]

    def get_test_command(self) -> Optional[list[str]]:
        return ["cmake", "--build", "build", "--target", "test"]

    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        return f"-D{feature}={'ON' if enabled else 'OFF'}"

    def validate_project(self) -> bool:
        return (
            (self.project_path / "CMakeLists.txt").exists()
            and (self.project_path / "src" / "amqp_management.c").exists()
        )

    def get_execution_commands(self, feature: str, enabled: bool) -> list[list[str]]:
        # azure-uamqp-c has unit tests via ctest
        return [["ctest", "--test-dir", "build", "--output-on-failure"]]
"""
Known features for azure-uamqp-c:
  - USE_WEBSOCKETS: WebSocket transport layer
  - USE_OPENSSL: OpenSSL TLS backend
  - USE_WOLFSSL: WolfSSL TLS backend
  - ENABLE_MOCKS: Test mock layer
"""
