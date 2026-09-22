"""
CMake project adapter for PRAT.

Handles conventional CMake boolean options without renaming them.
"""


from __future__ import annotations

from pathlib import Path

from ..compilation import BuildSystem
from .base import ProjectAdapter


class CMakeAdapter(ProjectAdapter):
    """
    Adapter for CMake-based projects.

    Build system: CMake
    Feature format: -DFEATURE=ON/OFF
    Coverage tool: gcov or llvm-cov (auto-detected)
    """

    @property
    def build_system(self) -> BuildSystem:
        """CMake projects use CMake."""
        return BuildSystem.CMAKE

    @property
    def coverage_tool(self) -> str:
        """CMake projects can use gcov or llvm-cov."""
        return "gcov"

    @property
    def source_directories(self) -> list[str]:
        """
        CMake source directories (project-specific).

        Default to common patterns, but may need customization.
        """
        return ["src", "lib"]

    def get_compile_command(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True
    ) -> list[str]:
        """
        Get CMake configuration command.

        Note: This returns the cmake command. Make must be run separately.
        Example: cmake -DCONFIG_TLS=1 -DCMAKE_BUILD_TYPE=Debug ..
        """
        cmd = ["cmake", "-S", ".", "-B", self.cmake_build_dir]

        # Add feature flag
        flag = self.format_feature_flag(feature, enabled)
        cmd.append(flag)

        # Add coverage flags
        if with_coverage:
            cmd.extend([
                "-DCMAKE_BUILD_TYPE=Debug",
                "-DCMAKE_C_FLAGS=--coverage",
                "-DCMAKE_CXX_FLAGS=--coverage"
            ])

        return cmd

    def get_build_commands(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True,
    ) -> list[list[str]]:
        """Configure from the project root, then build the binary directory."""
        return [
            self.get_compile_command(feature, enabled, with_coverage),
            ["cmake", "--build", self.cmake_build_dir, "--parallel"],
        ]

    def get_clean_command(self) -> list[str]:
        """Get clean command (remove build directory)."""
        return ["cmake", "-E", "remove_directory", self.cmake_build_dir]

    def get_test_command(self) -> list[str] | None:
        """Get CMake test command (CTest)."""
        return [
            "ctest", "--test-dir", self.cmake_build_dir, "--output-on-failure",
            "--no-tests=error",
        ]

    def normalize_feature_name(self, raw_option: str) -> str:
        """Keep the exact cache-variable name discovered from CMake."""
        return raw_option

    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        """
        Format a discovered CMake boolean without inventing a prefix.

        Args:
            feature: Feature name (e.g., "TLS", "SSL")
            enabled: True for 1, False for 0

        Returns:
            Formatted flag like "-DWITH_TLS=ON"
        """
        flag_value = "ON" if enabled else "OFF"
        return f"-D{feature}={flag_value}"

    def get_binary_path(self) -> str | None:
        """Get path to CMake build directory."""
        build_dir = self.project_path / self.cmake_build_dir
        if build_dir.exists():
            return str(build_dir)
        return None

    def get_build_directory(self) -> Path:
        """
        Get or create build directory for CMake.

        Returns:
            Path to build directory
        """
        build_dir = self.project_path / "build"
        build_dir.mkdir(exist_ok=True)
        return build_dir

    def get_make_command(self) -> list[str]:
        """
        Get make command to run after cmake.

        Returns:
            Make command with parallel jobs
        """
        return ["make", "-j3"]

    def validate_project(self) -> bool:
        """Validate this is a CMake project."""
        cmake_lists = self.project_path / "CMakeLists.txt"
        return cmake_lists.exists()
