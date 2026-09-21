"""
Base project adapter for PRAT.

Defines the common interface that all project adapters must implement.
"""


from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..compilation import BuildSystem


class ProjectAdapter(ABC):
    """
    Abstract base class for project-specific adapters.

    Each adapter encapsulates project-specific details like build commands,
    feature flag formats, source directories, and coverage tool preferences.
    """

    def __init__(self, project_path: str):
        """
        Initialize adapter with project path.

        Args:
            project_path: Path to project root directory
        """
        self.project_path = Path(project_path)

    @property
    def cmake_build_dir(self) -> str:
        """Name of the CMake binary directory (relative to project root).

        Defaults to "build". Override when a project ships its own top-level
        "build/" directory in source (e.g. libaom) that would collide with an
        out-of-source build named "build".
        """
        return "build"

    @property
    @abstractmethod
    def build_system(self) -> BuildSystem:
        """Return the build system used by this project."""
        pass

    @property
    @abstractmethod
    def coverage_tool(self) -> str:
        """Return the preferred coverage tool (gcov, llvm-cov, etc.)."""
        pass

    @property
    @abstractmethod
    def source_directories(self) -> list[str]:
        """Return list of source directories to analyze."""
        pass

    @abstractmethod
    def get_compile_command(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True
    ) -> list[str]:
        """
        Get compilation command for this project.

        Args:
            feature: Feature name to enable/disable
            enabled: True to enable feature, False to disable
            with_coverage: Whether to enable coverage instrumentation

        Returns:
            List of command arguments to execute
        """
        pass

    @abstractmethod
    def get_clean_command(self) -> list[str]:
        """
        Get clean command to remove build artifacts.

        Returns:
            List of command arguments to execute
        """
        pass

    @abstractmethod
    def get_test_command(self) -> list[str] | None:
        """
        Get test command to run test suite.

        Returns:
            List of command arguments, or None if no tests available
        """
        pass

    @abstractmethod
    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        """
        Format feature flag in project-specific format.

        Args:
            feature: Feature name
            enabled: True to enable, False to disable

        Returns:
            Formatted feature flag string
        """
        pass

    def get_binary_path(self) -> str | None:
        """
        Get path to compiled binary.

        Returns:
            Path to binary, or None if not applicable
        """
        return None

    def get_coverage_environment(self) -> dict[str, str]:
        """
        Get environment variables needed for coverage.

        Returns:
            Dictionary of environment variables
        """
        return {}

    def validate_project(self) -> bool:
        """
        Validate that this adapter is appropriate for the project.

        Returns:
        True if project structure matches adapter expectations
        """
        return self.project_path.exists()

    def get_build_commands(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True,
    ) -> list[list[str]]:
        """
        Return the full ordered sequence of commands to build the project.

        Default: a single-element list containing get_compile_command().
        Override for multi-step builds (e.g., FFmpeg: [configure, make]).

        Returns:
            Ordered list of commands; each command is a list of strings.
        """
        return [self.get_compile_command(feature, enabled, with_coverage)]

    def format_feature_flags(self, feature_states: dict[str, bool]) -> list[str]:
        """Format a whole set of feature states as build flags."""
        return [
            self.format_feature_flag(name, enabled)
            for name, enabled in sorted(feature_states.items())
        ]

    def supports_feature_sets(self) -> bool:
        """Whether this adapter can build an arbitrary set of feature states.

        Algorithm 1's baseline B_all has *all* features enabled and each B_i has
        all features enabled except f_i, which requires passing many flags in
        one build. Adapters whose build system takes flags as independent
        arguments get this for free from
        :meth:`get_build_commands_for_set`; those needing a different encoding
        (Cargo's single ``--features`` list, for instance) must override both.
        """
        return True

    def get_build_commands_for_set(
        self,
        feature_states: dict[str, bool],
        with_coverage: bool = True,
    ) -> list[list[str]]:
        """Build commands for an explicit set of feature states.

        The default splices every formatted flag into the single-feature command
        shape, which is correct for build systems that accept one independent
        argument per option (CMake ``-DX=ON``, autoconf ``--enable-x``, Make
        ``WITH_X=yes``).

        Args:
            feature_states: Feature name -> enabled. Must be non-empty.
            with_coverage: Whether to enable coverage instrumentation.
        """
        if not feature_states:
            raise ValueError("feature_states must not be empty")

        ordered = sorted(feature_states.items())
        anchor_name, anchor_enabled = ordered[0]

        commands = self.get_build_commands(anchor_name, anchor_enabled, with_coverage)
        if len(ordered) == 1:
            return commands

        extra = self.format_feature_flags(dict(ordered[1:]))
        anchor_flag = self.format_feature_flag(anchor_name, anchor_enabled)

        # Append the remaining flags to whichever command carries the anchor
        # flag, so configure-then-make pipelines put them on configure.
        spliced: list[list[str]] = []
        placed = False
        for command in commands:
            if not placed and anchor_flag in command:
                spliced.append(list(command) + extra)
                placed = True
            else:
                spliced.append(list(command))

        if not placed:
            spliced[0] = list(spliced[0]) + extra

        return spliced

    def get_execution_commands(self, feature: str, enabled: bool) -> list[list[str]]:
        """
        Get commands to execute the binary for dynamic coverage.

        Dynamic coverage requires actually running the compiled binary
        (or its test suite) so that .gcda profile data is generated.
        Override this in project-specific adapters.

        Args:
            feature: Feature being analyzed
            enabled: Whether the feature is enabled in this build

        Returns:
            List of commands to execute. Each command is a list of strings.
            Empty list means "just run the test suite" (default behavior).
        """
        # Default: if there's a test command, use that
        test_cmd = self.get_test_command()
        if test_cmd:
            return [test_cmd]
        return []
