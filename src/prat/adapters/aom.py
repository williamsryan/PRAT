"""
Adapter for AOM (libaom — AV1 codec reference implementation).

Project: https://aomedia.googlesource.com/aom
Build system: CMake
Features: CONFIG_AV1_ENCODER, CONFIG_AV1_DECODER, CONFIG_AV1_HIGHBITDEPTH, etc.
"""

from typing import Optional

from ..compilation import BuildSystem
from .base import ProjectAdapter


class AomAdapter(ProjectAdapter):
    """Adapter for AOM (libaom)."""

    @property
    def build_system(self) -> BuildSystem:
        return BuildSystem.CMAKE

    @property
    def coverage_tool(self) -> str:
        return "gcov"

    @property
    def cmake_build_dir(self) -> str:
        # libaom ships a top-level source directory "build/cmake/" that holds
        # its CMake helper modules. Using "build" as the out-of-source binary
        # directory collides with it and breaks include() of aom_configure.cmake.
        return "aom_build"

    @property
    def source_directories(self) -> list[str]:
        return ["aom", "aom_dsp", "av1"]

    def get_compile_command(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True,
    ) -> list[str]:
        """Return ONLY the cmake configure command (build is separate)."""
        flag_value = "1" if enabled else "0"
        cmd = [
            "cmake",
            "-B", self.cmake_build_dir,
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
        return cmd

    def get_build_commands(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True,
    ) -> list[list[str]]:
        """Configure then build as two separate commands (no shell chaining)."""
        configure = self.get_compile_command(feature, enabled, with_coverage)
        build = ["cmake", "--build", self.cmake_build_dir, "--parallel"]
        return [configure, build]

    def get_clean_command(self) -> list[str]:
        return ["rm", "-rf", self.cmake_build_dir]

    def get_test_command(self) -> Optional[list[str]]:
        # AOM test suite is heavy; use the testdata runner if available
        return None

    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        return f"-D{feature}={'1' if enabled else '0'}"

    def validate_project(self) -> bool:
        return (
            (self.project_path / "CMakeLists.txt").exists()
            and (self.project_path / "av1").exists()
        )

    def get_execution_commands(self, feature: str, enabled: bool) -> list[list[str]]:
        # Use compile-time coverage only (no execution), consistent with the
        # working Mosquitto/FFmpeg demos: gcov emits a .gcov from the .gcno
        # instrumentation graph alone, marking feature lines as removable. This
        # avoids depending on aomenc (which is not built when the encoder is
        # disabled) and keeps the enabled/disabled comparison purely structural.
        return []


"""
Known features for AOM (libaom):
  - CONFIG_AV1_ENCODER: AV1 encoder support
  - CONFIG_AV1_DECODER: AV1 decoder support
  - CONFIG_AV1_HIGHBITDEPTH: High bit-depth support
  - CONFIG_MULTITHREAD: Threading support
  - CONFIG_WEBM_IO: WebM container I/O
"""
