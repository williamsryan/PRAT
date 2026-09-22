"""Adapter for OpenDDS's configure/MPC build and compliance-profile features."""

from __future__ import annotations

from ..compilation import BuildSystem
from .base import ProjectAdapter

_COVERAGE_FLAGS = (
    "CCFLAGS += -fprofile-arcs -ftest-coverage\\n"
    "LDFLAGS += -fprofile-arcs -ftest-coverage\\n"
)
_PLATFORM_MACROS = "ACE_wrappers/include/makeinclude/platform_macros.GNU"

_FEATURE_FLAGS = {
    "content-filtered-topic": "content-filtered-topic",
    "persistence-profile": "persistence-profile",
    "ownership-kind-exclusive": "ownership-kind-exclusive",
    "query-condition": "query-condition",
    "ownership-profile": "ownership-profile",
}

_FEATURE_TESTS = {
    "content-filtered-topic": "tests/DCPS/ContentFilteredTopic/run_test.pl",
    "query-condition": "tests/DCPS/QueryCondition/run_test.pl",
    "ownership-profile": "tests/DCPS/Ownership/run_test.pl",
    "ownership-kind-exclusive": "tests/DCPS/Ownership/run_test.pl",
    "persistence-profile": "tests/DCPS/PersistentDurability/run_test.pl",
}


class OpenDDSAdapter(ProjectAdapter):
    """Build OpenDDS with the same feature switches used by the paper."""

    @property
    def build_system(self) -> BuildSystem:
        return BuildSystem.MPC

    @property
    def coverage_tool(self) -> str:
        return "gcov"

    @property
    def cmake_build_dir(self) -> str:
        return "dds"

    @property
    def source_directories(self) -> list[str]:
        return ["dds"]

    def normalize_feature_name(self, raw_option: str) -> str:
        normalized = raw_option.lower()
        return normalized[3:] if normalized.startswith("no-") else normalized

    def _flag(self, feature: str, enabled: bool) -> str:
        normalized = self.normalize_feature_name(feature)
        option = _FEATURE_FLAGS.get(normalized)
        if option is None:
            supported = ", ".join(sorted(_FEATURE_FLAGS))
            raise ValueError(
                f"Unsupported OpenDDS feature '{feature}'; supported: {supported}"
            )
        return f"--{option}" if enabled else f"--no-{option}"

    def _build_script(
        self,
        feature_states: dict[str, bool],
        with_coverage: bool,
    ) -> str:
        flags = " ".join(
            self._flag(feature, enabled)
            for feature, enabled in sorted(feature_states.items())
        )
        coverage = (
            f"printf '{_COVERAGE_FLAGS}' >> {_PLATFORM_MACROS}; "
            if with_coverage
            else ""
        )
        return (
            "set -e; "
            f"./configure --prefix=/usr/local --tests {flags} --doc-group; "
            f"{coverage}"
            ". ./setenv.sh; "
            'make -j"$(nproc)"'
        )

    def get_compile_command(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True,
    ) -> list[str]:
        return [
            "bash",
            "-lc",
            self._build_script(
                {self.normalize_feature_name(feature): enabled},
                with_coverage,
            ),
        ]

    def get_build_commands(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True,
    ) -> list[list[str]]:
        return [self.get_compile_command(feature, enabled, with_coverage)]

    def get_build_commands_for_set(
        self,
        feature_states: dict[str, bool],
        with_coverage: bool = True,
    ) -> list[list[str]]:
        normalized = {
            self.normalize_feature_name(feature): enabled
            for feature, enabled in feature_states.items()
        }
        return [["bash", "-lc", self._build_script(normalized, with_coverage)]]

    def get_clean_command(self) -> list[str]:
        return ["bash", "-lc", "git clean -fdxq -e .git"]

    def get_test_command(self) -> list[str] | None:
        return None

    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        return self._flag(feature, enabled)

    def validate_project(self) -> bool:
        return (
            (self.project_path / "configure").exists()
            and (self.project_path / "dds").exists()
            and (self.project_path / "DDS.mwc").exists()
        )

    def get_execution_commands(self, feature: str, enabled: bool) -> list[list[str]]:
        normalized = self.normalize_feature_name(feature)
        test = _FEATURE_TESTS.get(normalized)
        if test is None:
            raise ValueError(f"No OpenDDS test suite mapped for '{feature}'")
        return [["bash", "-lc", f". ./setenv.sh; perl {test}"]]
