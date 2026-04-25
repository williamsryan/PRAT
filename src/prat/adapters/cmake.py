"""
CMake project adapter for PRAT.

Handles CMake-based builds with -DCONFIG_FEATURE=1/0 flags.
"""

from pathlib import Path
from typing import Optional

from ..compilation import BuildSystem
from .base import ProjectAdapter


class CMakeAdapter(ProjectAdapter):
    """
    Adapter for CMake-based projects.

    Build system: CMake
    Feature format: -DCONFIG_FEATURE=1/0
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
        cmd = ["cmake"]

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

        # Reference parent directory (assumes build/ subdirectory)
        cmd.append("..")

        return cmd

    def get_clean_command(self) -> list[str]:
        """Get clean command (remove build directory)."""
        # CMake clean is typically done by removing build directory
        # For now, return make clean which works in build directory
        return ["make", "clean"]

    def get_test_command(self) -> Optional[list[str]]:
        """Get CMake test command (CTest)."""
        return ["ctest", "--output-on-failure"]

    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        """
        Format feature flag as -DCONFIG_FEATURE=1/0.

        Args:
            feature: Feature name (e.g., "TLS", "SSL")
            enabled: True for 1, False for 0

        Returns:
            Formatted flag like "-DCONFIG_TLS=1"
        """
        flag_value = "1" if enabled else "0"
        return f"-DCONFIG_{feature.upper()}={flag_value}"

    def get_binary_path(self) -> Optional[str]:
        """Get path to CMake build directory."""
        build_dir = self.project_path / "build"
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
