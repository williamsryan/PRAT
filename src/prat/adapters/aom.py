"""
Adapter for AOM (libaom — AV1 codec reference implementation).

Project: https://aomedia.googlesource.com/aom
Build system: CMake
Features: CONFIG_AV1_ENCODER, CONFIG_AV1_DECODER, CONFIG_AV1_HIGHBITDEPTH, etc.
"""


from __future__ import annotations

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
        return ["cmake", "-E", "remove_directory", self.cmake_build_dir]

    def get_test_command(self) -> list[str] | None:
        # AOM test suite is heavy; use the testdata runner if available
        return None

    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        return f"-D{feature}={'1' if enabled else '0'}"

    def validate_project(self) -> bool:
        return (
            (self.project_path / "CMakeLists.txt").exists()
            and (self.project_path / "av1").exists()
        )

    def _test_clip_commands(self) -> tuple[list[str], list[list[str]], list[list[str]]]:
        """(input generator, encoder commands, decoder commands) for the clip."""
        bd = self.cmake_build_dir
        gen_input = [
            "sh", "-c",
            "printf 'YUV4MPEG2 W176 H144 F30:1 Ip A1:1 C420\\n' > /tmp/aom_in.y4m && "
            "for i in $(seq 1 12); do printf 'FRAME\\n' >> /tmp/aom_in.y4m && "
            "head -c 38016 /dev/zero >> /tmp/aom_in.y4m; done",
        ]
        encode = [
            # cpu-used=2 exercises a broad set of RD/partition/transform paths
            # without being prohibitively slow on a 12-frame clip.
            [f"{bd}/aomenc", "--codec=av1", "--ivf", "--limit=12", "--cpu-used=2",
             "-o", "/tmp/aom_out.ivf", "/tmp/aom_in.y4m"],
            # A lossless pass exercises additional encoder code paths.
            [f"{bd}/aomenc", "--codec=av1", "--ivf", "--limit=6", "--cpu-used=4",
             "--lossless=1", "-o", "/tmp/aom_ll.ivf", "/tmp/aom_in.y4m"],
        ]
        decode = [
            [f"{bd}/aomdec", "--codec=av1", "-o", "/tmp/aom_dec.y4m", "/tmp/aom_out.ivf"],
        ]
        return gen_input, encode, decode

    def get_test_plan(self, features: list[str]) -> list[list[str]]:
        """The fixed T: synthesize a clip, encode it twice, decode it.

        The same four commands run against B_all and every B_f. In a build
        without the encoder ``aomenc`` does not exist and those commands fail;
        the mapping tolerates that and takes coverage from ``aomdec``, which
        decodes the stream the B_all run left in /tmp (the container spans both
        builds). Likewise a decoder-less build contributes encoder coverage
        only. This is what makes coverage DYNAMIC: static (compile-time)
        coverage marks every line in the dedicated encoder files as removable,
        massively over-counting against the paper's KLEE/dynamic methodology.
        """
        gen_input, encode, decode = self._test_clip_commands()
        return [gen_input, *encode, *decode]

    def get_execution_commands(self, feature: str, enabled: bool) -> list[list[str]]:
        """Polarity-specific workload, used for post-removal verification.

        - feature ENABLED  (encoder built): the full :meth:`get_test_plan`.
        - feature DISABLED (decoder only): decode the clip produced during the
          enabled run, which is what a debloated decoder-only build must still
          be able to do.
        """
        gen_input, encode, decode = self._test_clip_commands()
        bd = self.cmake_build_dir
        if enabled:
            return [gen_input, *encode, *decode]
        return [
            [f"{bd}/aomdec", "--codec=av1", "-o", "/tmp/aom_dec2.y4m", "/tmp/aom_out.ivf"],
        ]


"""
Known features for AOM (libaom):
  - CONFIG_AV1_ENCODER: AV1 encoder support
  - CONFIG_AV1_DECODER: AV1 decoder support
  - CONFIG_AV1_HIGHBITDEPTH: High bit-depth support
  - CONFIG_MULTITHREAD: Threading support
  - CONFIG_WEBM_IO: WebM container I/O
"""
