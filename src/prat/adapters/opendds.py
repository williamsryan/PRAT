"""
Adapter for OpenDDS (DDS implementation in C++).

Project: https://github.com/OpenDDS/OpenDDS
Build system: OpenDDS is NOT a CMake-root project. It builds via a Perl
`configure` script + MPC (MakeProjectCreator) on top of ACE/TAO. The DDS
Security subsystem is a configure-time switch (`./configure --security`), which
compiles `dds/DCPS/security/*` and activates `#ifdef OPENDDS_SECURITY` hooks in
shared DDS sources.

Differential strategy for the SECURITY feature:
  - ENABLED:  ./configure --security --doc-group  → security sources compiled
  - DISABLED: ./configure            --doc-group  → security sources absent
Each build is a full ACE+TAO+OpenDDS compile (~5-7 min with `make -j`), so the
two configs are built independently from a pristine tree.

Coverage: `--coverage` flags are appended to ACE's generated
`platform_macros.GNU` *after* configure (configure regenerates that file), so
the whole tree is instrumented. gcov records absolute source paths, so the
generic ".gcno rglob" coverage path (shared with CMake) resolves sources from
the `.shobj/`/`.obj/` object dirs. We therefore report `build_system = CMAKE`
purely to route coverage through that rglob path and point it at `dds/`.
"""

from typing import Optional

from ..compilation import BuildSystem
from .base import ProjectAdapter

# Coverage flags appended to ACE's platform_macros.GNU after configure.
_COVERAGE_FLAGS = (
    "CCFLAGS += -fprofile-arcs -ftest-coverage\\n"
    "LDFLAGS += -fprofile-arcs -ftest-coverage\\n"
)
_PLATFORM_MACROS = "ACE_wrappers/include/makeinclude/platform_macros.GNU"


class OpenDDSAdapter(ProjectAdapter):
    """Adapter for OpenDDS (configure + MPC build of ACE/TAO + OpenDDS)."""

    @property
    def build_system(self) -> BuildSystem:
        # Reported as CMAKE only so coverage is generated via the generic
        # ".gcno rglob" path (see coverage._generate_coverage_cmake), pointed at
        # `cmake_build_dir` below. The actual build is configure + MPC `make`.
        return BuildSystem.CMAKE

    @property
    def coverage_tool(self) -> str:
        return "gcov"

    @property
    def cmake_build_dir(self) -> str:
        # OpenDDS object/.gcno files live under dds/**/.shobj and dds/**/.obj.
        # Pointing the rglob coverage scan at dds/ captures the DDS library
        # (including the dedicated security subsystem) without ACE/TAO noise.
        return "dds"

    @property
    def source_directories(self) -> list[str]:
        return ["dds"]

    def _build_script(self, enabled: bool) -> str:
        security = "--security " if enabled else ""
        return (
            "set -e; "
            f"./configure --prefix=/usr/local {security}--doc-group; "
            f"printf '{_COVERAGE_FLAGS}' >> {_PLATFORM_MACROS}; "
            ". ./setenv.sh; "
            'make -j"$(nproc)"'
        )

    def get_compile_command(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True,
    ) -> list[str]:
        return ["bash", "-lc", self._build_script(enabled)]

    def get_build_commands(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True,
    ) -> list[list[str]]:
        # Single command: configure (with/without --security) + inject coverage
        # + make. Run from the OpenDDS root (compile_with_adapter sets cwd).
        return [self.get_compile_command(feature, enabled, with_coverage)]

    def get_clean_command(self) -> list[str]:
        # Restore a pristine tree between the two configs: remove everything
        # untracked (ACE_wrappers, generated makefiles, .obj/.shobj, *.gcno) so
        # the next ./configure starts clean. The clone keeps its .git.
        return ["bash", "-lc", "git clean -fdxq -e .git 2>/dev/null || true"]

    def get_test_command(self) -> Optional[list[str]]:
        return None

    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        return "--security" if enabled else ""

    def validate_project(self) -> bool:
        # OpenDDS has NO top-level CMakeLists.txt; detect it by its Perl
        # configure script + the dds/ tree + its MPC workspace file.
        return (
            (self.project_path / "configure").exists()
            and (self.project_path / "dds").exists()
            and (self.project_path / "DDS.mwc").exists()
        )

    def get_execution_commands(self, feature: str, enabled: bool) -> list[list[str]]:
        # Compile-time coverage (no execution): gcov emits removable (#####)
        # lines from the .gcno graph alone. Running the full OpenDDS security
        # test suite would require a multi-process DDS environment that is out
        # of scope for the differential build.
        return []


"""
Known features for OpenDDS:
  - SECURITY: DDS Security specification support (OpenSSL + Xerces-C)
  - CONTENT_SUBSCRIPTION: Content-filtered topics
  - PERSISTENCE: Durable subscriptions
  - BUILT_IN_TOPICS: Built-in topic support
"""
