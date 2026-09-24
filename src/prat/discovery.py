"""
Feature identification module for PRAT.

Paper, Feature Identification, defines a feature as "a set of lines of code which
can be selectively activated or deactivated by operating on a single build
configuration option", and describes one analyzer per build system:

*cMake* — "The analyzer builds the root project in the source tree using
``cmake -LA | grep BOOL``, which returns a list of toggleable options. We posit
that a feature which can only assume boolean values true or false corresponds to
a user-defined feature."

*Autoconf* — "The analyzer obtains a list of build-time options by executing
``configure --help``, and retains those whose description includes the words
'feature' or 'optional'."

*Cargo* — "The analyzer parses ``Cargo.toml`` to find any defined features and
returns a list of those that are non-default."

*Make* — Mosquitto-style ``WITH_*`` toggles declared in ``config.mk``/``Makefile``.

Followed by a filtering stage: "Most of these spurious options are standard
across codebases and are automatically discarded by our parser. We further apply
filters to hide features that are meant for debugging or other developer-specific
options." That is :func:`filter_features`.

Two structural points. First, a project can expose features through more than one
build system — Mosquitto ships both ``CMakeLists.txt`` and ``config.mk``, and its
``WITH_BRIDGE``/``WITH_PERSISTENCE`` toggles exist only in the latter — so
:func:`discover_features` runs every analyzer that applies and merges the
results rather than taking the first that matches. Second, discovery reports the
build option verbatim in :attr:`Feature.raw_name`; translating that into a
command-line flag is the adapter's job, since the same option is spelled
``WITH_TLS=yes`` for Make and ``-DWITH_TLS=ON`` for CMake.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Feature:
    """A discovered, build-toggleable feature."""

    name: str
    description: str | None = None
    default_enabled: bool | None = None
    #: The build option exactly as the build system spells it (e.g.
    #: ``WITH_TLS``, ``CONFIG_AV1_ENCODER``, ``use_wsio``). ``name`` may be a
    #: normalized form of this.
    raw_name: str | None = None
    #: Which analyzer produced this feature ("cmake", "autotools", ...).
    source: str | None = None
    #: Why the feature was filtered out, when it was.
    filtered_reason: str | None = None

    def __post_init__(self) -> None:
        if self.raw_name is None:
            self.raw_name = self.name


# Build options that are standard across codebases and control compilation
# mechanics rather than program functionality. The paper reports exactly one
# false positive across its dataset — "the option to build with or without a
# shared library" — so options of this kind are discarded by name.
_STANDARD_OPTIONS = frozenset({
    "BUILD_SHARED_LIBS", "SHARED_LIBRARIES", "STATIC_LIBRARIES", "BUILD_STATIC",
    "BUILD_SHARED", "ENABLE_SHARED", "ENABLE_STATIC", "PIC", "BUILD_PIC",
    "BUNDLED_DEPS", "USE_BUNDLED", "INSTALL", "BUILD_INSTALL",
    "DOCUMENTATION", "BUILD_DOCS", "DOCS", "BUILD_DOC", "MANPAGES",
    "BUILD_TESTS", "BUILD_TESTING", "TESTS", "ENABLE_TESTS", "BUILD_EXAMPLES",
    "EXAMPLES", "BUILD_SAMPLES", "SAMPLES", "BUILD_BENCHMARKS", "BENCHMARKS",
    "LTO", "IPO", "OPTIMIZATION", "FAST_MATH", "NATIVE",
    "RPATH", "SOVERSION", "VERSIONED", "PKGCONFIG", "PKG_CONFIG",
    "CROSS_COMPILING", "CMAKE_BUILD_TYPE", "BUILD_TYPE", "VERBOSE_MAKEFILE",
    "DEPENDENCY_TRACKING", "SILENT_RULES", "OPTION_CHECKING",
    "FAST_INSTALL", "LIBTOOL_LOCK", "MAINTAINER_MODE",
})

# Substrings marking debugging or developer-specific options, which the paper
# filters out by naming convention.
_DEVELOPER_MARKERS = (
    "DEBUG", "ASSERT", "SANITIZ", "ASAN", "MSAN", "TSAN", "UBSAN",
    "COVERAGE", "GCOV", "PROFIL", "GPROF", "TRACE", "VALGRIND",
    "WERROR", "WARNINGS", "PEDANTIC", "STRIP", "SYMBOLS",
    "FUZZ", "FUZZING", "DEVELOPER", "DEV_MODE", "INTERNAL_TESTS",
)

# Option-name prefixes that adapters commonly add back when formatting a flag.
_FEATURE_PREFIXES = ("CONFIG_", "WITH_", "ENABLE_", "USE_")

# Prefixes owned by the build system itself rather than the project. A
# ``cmake -LA`` listing includes CMake's own boolean cache variables
# (CMAKE_VERBOSE_MAKEFILE, CMAKE_SKIP_RPATH, ...), which are "standard across
# codebases" in exactly the sense the paper's filter describes: they control how
# the build runs and map to no source code.
_BUILD_SYSTEM_PREFIXES = ("CMAKE_", "CPACK_", "CTEST_", "CMAKE3_")


def strip_feature_prefix(name: str) -> str:
    """Remove a leading ``CONFIG_``/``WITH_``/``ENABLE_``/``USE_`` prefix."""
    upper = name.upper()
    for prefix in _FEATURE_PREFIXES:
        if upper.startswith(prefix):
            return name[len(prefix):]
    return name


def is_standard_option(name: str) -> bool:
    """Whether a build option controls compilation mechanics, not functionality."""
    normalized = name.upper().replace("-", "_")
    if normalized.startswith(_BUILD_SYSTEM_PREFIXES):
        return True
    if normalized in _STANDARD_OPTIONS:
        return True
    return strip_feature_prefix(normalized).upper() in _STANDARD_OPTIONS


def is_developer_option(name: str, description: str | None = None) -> bool:
    """Whether a build option is for debugging or developer use."""
    normalized = name.upper().replace("-", "_")
    if any(marker in normalized for marker in _DEVELOPER_MARKERS):
        return True
    if description:
        lowered = description.lower()
        return any(
            phrase in lowered
            for phrase in ("debugging", "debug build", "for developers",
                           "developer only", "not for production")
        )
    return False


def filter_features(
    features: list[Feature],
    keep_developer_options: bool = False,
) -> tuple[list[Feature], list[Feature]]:
    """Split discovered options into candidate features and discarded ones.

    Implements the paper's filtering stage: standard compilation options are
    discarded as spurious, and debugging/developer options are hidden.

    Args:
        features: Raw discovery output.
        keep_developer_options: Retain debug/developer options. The paper's
            default behaviour is to hide them.

    Returns:
        ``(candidates, discarded)``. Each discarded feature carries a
        ``filtered_reason`` so the decision is auditable rather than silent.
    """
    candidates: list[Feature] = []
    discarded: list[Feature] = []

    for feature in features:
        raw = feature.raw_name or feature.name

        if is_standard_option(raw):
            feature.filtered_reason = "standard build option, not a program feature"
            discarded.append(feature)
            continue

        if not keep_developer_options and is_developer_option(raw, feature.description):
            feature.filtered_reason = "debugging or developer-specific option"
            discarded.append(feature)
            continue

        candidates.append(feature)

    return candidates, discarded


def discover_features(
    project_path: str,
    adapter: Any | None = None,
    apply_filters: bool = True,
    keep_developer_options: bool = False,
) -> list[Feature]:
    """
    Discover the candidate feature set of a project.

    Every analyzer whose build system is present is run and the results merged,
    because a project can expose different features through different build
    systems.

    Args:
        project_path: Path to project root directory.
        adapter: Optional ProjectAdapter used to normalize option names into the
            form its ``format_feature_flag`` expects.
        apply_filters: Apply the paper's spurious/developer-option filtering.
        keep_developer_options: Retain debug/developer options when filtering.

    Returns:
        List of candidate features.
    """
    project = Path(project_path)
    discovered: list[Feature] = []

    if (project / "CMakeLists.txt").exists():
        discovered.extend(discover_features_cmake(project_path))
    if (project / "configure").exists() or (project / "configure.ac").exists():
        discovered.extend(discover_features_autotools(project_path))
    if (project / "Cargo.toml").exists():
        discovered.extend(discover_features_cargo(project_path))
    if (project / "Makefile").exists() or (project / "config.mk").exists():
        discovered.extend(discover_features_make(project_path))

    merged = _merge_features(discovered)

    if adapter is not None and hasattr(adapter, "normalize_feature_name"):
        for feature in merged:
            feature.name = adapter.normalize_feature_name(
                feature.raw_name or feature.name
            )
        merged = _merge_features(merged)

    if not apply_filters:
        return merged

    candidates, discarded = filter_features(
        merged, keep_developer_options=keep_developer_options
    )

    if discarded:
        print(f"[+] Filtered {len(discarded)} non-feature build option(s)")
        for feature in discarded[:10]:
            print(f"      {feature.raw_name}: {feature.filtered_reason}")
        if len(discarded) > 10:
            print(f"      ... and {len(discarded) - 10} more")

    return candidates


def _merge_features(features: list[Feature]) -> list[Feature]:
    """Deduplicate by raw option name, preferring entries with a description."""
    merged: dict[str, Feature] = {}

    for feature in features:
        key = (feature.raw_name or feature.name).upper()
        existing = merged.get(key)
        if existing is None:
            merged[key] = feature
            continue
        if not existing.description and feature.description:
            existing.description = feature.description
        if existing.default_enabled is None and feature.default_enabled is not None:
            existing.default_enabled = feature.default_enabled

    return sorted(merged.values(), key=lambda item: item.name.upper())


# ---------------------------------------------------------------------------
# cMake
# ---------------------------------------------------------------------------


def discover_features_cmake(project_path: str) -> list[Feature]:
    """
    Discover features in CMake projects.

    Primary mechanism is the paper's: configure the project and read
    ``cmake -LA``, keeping the options whose cache type is ``BOOL``. Configuring
    into a scratch directory is required — ``cmake -LA -N`` only prints an
    existing cache, so on a clean tree it reports nothing at all.

    ``CMakeLists.txt`` is parsed as well, for two reasons: it supplies the
    human-readable descriptions that ``-LA`` omits, and it covers projects whose
    options are declared with ``set(... CACHE BOOL ...)`` or a project-specific
    macro rather than ``option()``.
    """
    project = Path(project_path)
    if not (project / "CMakeLists.txt").exists():
        return []

    features = _cmake_features_from_cache(project_path)
    declared = _cmake_features_from_sources(project)

    # -LA is authoritative for *which* options exist and are boolean; the source
    # scan supplies descriptions and fills in options a configure run missed.
    by_name = {(f.raw_name or f.name).upper(): f for f in features}
    for feature in declared:
        key = (feature.raw_name or feature.name).upper()
        if key in by_name:
            if not by_name[key].description:
                by_name[key].description = feature.description
        else:
            by_name[key] = feature

    return sorted(by_name.values(), key=lambda item: item.name.upper())


def _cmake_features_from_cache(project_path: str) -> list[Feature]:
    """Configure into a scratch build dir and read boolean cache entries."""
    if not shutil.which("cmake"):
        return []

    features: list[Feature] = []

    with tempfile.TemporaryDirectory(prefix="prat-cmake-") as build_dir:
        try:
            configure = subprocess.run(
                # CMake >= 4 refuses projects whose cmake_minimum_required is
                # below 3.5 (Mosquitto 2.0.x declares 3.0); this flag lets the
                # configure proceed so the cache can be listed. It is what the
                # Mosquitto adapter passes for the real build as well.
                ["cmake", "-S", str(project_path), "-B", build_dir,
                 "-DCMAKE_POLICY_VERSION_MINIMUM=3.5"],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if configure.returncode != 0:
                detail = (configure.stderr or "").strip().splitlines()
                print(f"[!] cmake configure failed during discovery: "
                      f"{detail[-1][:160] if detail else 'unknown error'}")
                return []

            listing = subprocess.run(
                ["cmake", "-LA", "-N", "-B", build_dir],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if listing.returncode != 0:
                return []
        except (subprocess.TimeoutExpired, OSError, subprocess.SubprocessError) as exc:
            print(f"[!] cmake discovery unavailable: {exc}")
            return []

        # "NAME:BOOL=ON" — the paper's `cmake -LA | grep BOOL`.
        pattern = re.compile(r"^([A-Za-z0-9_\-]+):BOOL=(\w+)\s*$")
        for line in listing.stdout.splitlines():
            match = pattern.match(line.strip())
            if not match:
                continue
            name, value = match.group(1), match.group(2).upper()
            features.append(Feature(
                name=name,
                raw_name=name,
                default_enabled=value in ("ON", "TRUE", "YES", "1"),
                source="cmake",
            ))

    return features


_CMAKE_SOURCE_GLOBS = ("CMakeLists.txt", "cmake/*.cmake", "build/cmake/*.cmake")


def _cmake_features_from_sources(project: Path) -> list[Feature]:
    """Scan CMake sources for boolean option declarations.

    Covers ``option(NAME "desc" ON)``, ``set(NAME val CACHE BOOL "desc")`` and
    ``*_config_var(NAME default "desc")`` helper macros (libaom declares every
    ``CONFIG_*`` toggle through ``set_aom_config_var``, so an ``option()``-only
    scan finds none of them).
    """
    features: list[Feature] = []

    option_re = re.compile(
        r'\boption\s*\(\s*([A-Za-z0-9_]+)\s+"([^"]*)"(?:\s+(\w+))?\s*\)',
        re.IGNORECASE,
    )
    cache_bool_re = re.compile(
        r'\bset\s*\(\s*([A-Za-z0-9_]+)\s+(\S+)\s+CACHE\s+BOOL\s+"([^"]*)"',
        re.IGNORECASE,
    )
    config_var_re = re.compile(
        r'\b\w*config_var\s*\(\s*([A-Za-z0-9_]+)\s+(\S+)\s+"([^"]*)"',
        re.IGNORECASE,
    )

    def truthy(value: str) -> bool | None:
        cleaned = value.strip('"\'').upper()
        if cleaned in ("ON", "TRUE", "YES", "1"):
            return True
        if cleaned in ("OFF", "FALSE", "NO", "0"):
            return False
        return None

    for pattern_glob in _CMAKE_SOURCE_GLOBS:
        for path in sorted(project.glob(pattern_glob)):
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            for match in option_re.finditer(content):
                features.append(Feature(
                    name=match.group(1),
                    raw_name=match.group(1),
                    description=match.group(2) or None,
                    default_enabled=truthy(match.group(3) or ""),
                    source="cmake",
                ))

            for match in cache_bool_re.finditer(content):
                features.append(Feature(
                    name=match.group(1),
                    raw_name=match.group(1),
                    description=match.group(3) or None,
                    default_enabled=truthy(match.group(2)),
                    source="cmake",
                ))

            for match in config_var_re.finditer(content):
                default = truthy(match.group(2))
                if default is None:
                    continue  # not a boolean toggle
                features.append(Feature(
                    name=match.group(1),
                    raw_name=match.group(1),
                    description=match.group(3) or None,
                    default_enabled=default,
                    source="cmake",
                ))

    return features


# ---------------------------------------------------------------------------
# Autoconf
# ---------------------------------------------------------------------------

#: The paper keeps options "whose description includes the words 'feature' or
#: 'optional'". Matched as whole words so "optionally" and "features" count but
#: "functional" does not.
_FEATURE_WORD_RE = re.compile(r"\b(?:feature|features|optional|optionally)\b", re.I)


def discover_features_autotools(
    project_path: str,
    require_feature_wording: bool = True,
) -> list[Feature]:
    """
    Discover features from ``configure --help``.

    Args:
        project_path: Path to project root directory.
        require_feature_wording: Apply the paper's filter — retain only options
            whose help text mentions "feature" or "optional". FFmpeg's
            ``configure`` alone lists hundreds of ``--enable-*`` switches, most
            of them individual codecs and build knobs, so without this filter
            the candidate set bears no relation to the paper's counts.

    Returns:
        List of discovered features.
    """
    project = Path(project_path)
    configure = project / "configure"

    if not configure.exists():
        return []

    help_text = _configure_help(project_path, configure)
    if not help_text:
        return []

    return _parse_configure_help(help_text, require_feature_wording)


def _configure_help(project_path: str, configure: Path) -> str | None:
    """Run ``configure --help``, honouring the script's own interpreter.

    OpenDDS's ``configure`` is a Perl script, so forcing ``bash`` fails. Execute
    it directly and let the shebang decide; fall back to bash only if that is
    not possible.
    """
    attempts: list[list[str]] = []

    if os.access(configure, os.X_OK):
        attempts.append([str(configure), "--help"])

    try:
        first_line = configure.open("r", errors="ignore").readline()
    except OSError:
        first_line = ""

    if first_line.startswith("#!"):
        interpreter = first_line[2:].strip().split()
        if interpreter:
            program = os.path.basename(interpreter[0])
            if program == "env" and len(interpreter) > 1:
                program = interpreter[1]
            if shutil.which(program):
                attempts.append([program, str(configure), "--help"])

    attempts.append(["bash", str(configure), "--help"])

    for command in attempts:
        try:
            proc = subprocess.run(
                command,
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (subprocess.TimeoutExpired, OSError, subprocess.SubprocessError):
            continue

        output = proc.stdout + proc.stderr
        # Some configure scripts exit non-zero on --help but still print it.
        if "--enable-" in output or "--disable-" in output:
            return output

    print("[!] configure --help produced no option list")
    return None


def _parse_configure_help(
    help_text: str,
    require_feature_wording: bool,
) -> list[Feature]:
    """Parse ``--enable-*``/``--disable-*`` options and their descriptions."""
    features: dict[str, Feature] = {}

    # Option token, then its description, which may continue on wrapped lines
    # until the next option or a blank line.
    entry_re = re.compile(
        r"^\s*--(enable|disable)-([A-Za-z0-9_][A-Za-z0-9_.\-]*)"
        r"(?:\[?=\S*\]?)?\s*(.*?)$"
    )

    lines = help_text.splitlines()
    index = 0
    while index < len(lines):
        match = entry_re.match(lines[index])
        if not match:
            index += 1
            continue

        polarity, raw_name, description = match.groups()
        index += 1

        # Absorb continuation lines: indented text that is not a new option.
        while index < len(lines):
            nxt = lines[index]
            if not nxt.strip() or nxt.lstrip().startswith("-"):
                break
            description += " " + nxt.strip()
            index += 1

        description = re.sub(r"\s+", " ", description).strip()

        # Strip any "=NAME"/"=VALUE" placeholder left in the option token, which
        # would otherwise yield feature names like "decoder=NAME".
        name = raw_name.split("=")[0].strip("[]")
        if not name:
            continue

        if require_feature_wording and not _FEATURE_WORD_RE.search(description):
            continue

        key = name.upper()
        if key in features:
            if not features[key].description and description:
                features[key].description = description
            continue

        features[key] = Feature(
            name=name.upper(),
            raw_name=name,
            description=description or None,
            # "--disable-x" implies x is on by default, and vice versa.
            default_enabled=(polarity == "disable"),
            source="autotools",
        )

    return sorted(features.values(), key=lambda item: item.name)


# ---------------------------------------------------------------------------
# Cargo
# ---------------------------------------------------------------------------


def discover_features_cargo(project_path: str) -> list[Feature]:
    """
    Discover non-default features from ``Cargo.toml``.

    The paper returns "those that are non-default", so features listed in the
    ``default`` array are excluded, not merely flagged: they are enabled in every
    ordinary build, so toggling one is not an optional-feature decision.

    Also reads workspace members, since Cargo workspaces (quiche, rav1e) declare
    features in the member crate rather than the root manifest.
    """
    project = Path(project_path)
    manifests = [project / "Cargo.toml"]

    if not manifests[0].exists():
        return []

    manifests.extend(_cargo_member_manifests(project))

    features: dict[str, Feature] = {}

    for manifest in manifests:
        table, default_members = _read_cargo_features(manifest)
        for name, deps in table.items():
            if name == "default" or name in default_members:
                continue
            key = name.upper()
            if key in features:
                continue
            features[key] = Feature(
                name=name.upper(),
                raw_name=name,
                description=(f"Enables: {', '.join(deps)}" if deps else None),
                default_enabled=False,
                source="cargo",
            )

    return sorted(features.values(), key=lambda item: item.name)


def _cargo_member_manifests(project: Path) -> list[Path]:
    """Manifests of workspace members declared in the root Cargo.toml."""
    try:
        content = (project / "Cargo.toml").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    members_match = re.search(
        r"\[workspace\][^\[]*?members\s*=\s*\[(.*?)\]", content, re.S
    )
    if not members_match:
        return []

    manifests: list[Path] = []
    for entry in re.findall(r'"([^"]+)"', members_match.group(1)):
        for candidate in sorted(project.glob(entry)):
            manifest = candidate / "Cargo.toml"
            if manifest.is_file():
                manifests.append(manifest)
    return manifests


def _read_cargo_features(manifest: Path) -> tuple[dict[str, list[str]], set[str]]:
    """Return ``({feature: deps}, default_member_names)`` from a manifest.

    Uses a TOML parser when one is available (``tomllib`` on 3.11+), and a regex
    fallback otherwise. Both paths compute the default set, so the result does
    not depend on which is used.
    """
    table: dict[str, list[str]] = {}

    # tomllib is stdlib from 3.11; tomli is the backport for 3.9/3.10. Either
    # gives a correct parse, and the regex fallback below covers neither being
    # present, so the computed default set does not depend on which is used.
    parser: Any | None
    try:
        import tomllib as parser  # type: ignore[import-not-found,no-redef]
    except ImportError:
        try:
            import tomli as parser  # type: ignore[import-not-found,no-redef]
        except ImportError:
            parser = None

    if parser is not None:
        try:
            with manifest.open("rb") as handle:
                data = parser.load(handle)
            raw = data.get("features", {})
            for name, deps in raw.items():
                table[name] = [str(dep) for dep in (deps or [])]
        except (OSError, ValueError):
            table = {}

    if not table:
        try:
            content = manifest.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return {}, set()

        section = re.search(r"^\[features\]\s*$(.*?)(?=^\[|\Z)",
                            content, re.M | re.S)
        if not section:
            return {}, set()

        for match in re.finditer(
            r"^\s*([A-Za-z0-9_\-]+)\s*=\s*\[(.*?)\]",
            section.group(1),
            re.M | re.S,
        ):
            name = match.group(1)
            deps = re.findall(r'"([^"]*)"', match.group(2))
            table[name] = deps

    default_members = {dep for dep in table.get("default", [])}
    # A default feature may itself pull in others; those are equally non-optional.
    frontier = list(default_members)
    while frontier:
        current = frontier.pop()
        for dep in table.get(current, []):
            if dep in table and dep not in default_members:
                default_members.add(dep)
                frontier.append(dep)

    return table, default_members


# ---------------------------------------------------------------------------
# Make
# ---------------------------------------------------------------------------


def discover_features_make(project_path: str) -> list[Feature]:
    """
    Discover ``WITH_*`` toggles from ``config.mk``/``Makefile``.

    Mosquitto is the paper's Make-based target and declares every optional
    feature here as ``WITH_<NAME>:=yes|no``, including several (BRIDGE,
    PERSISTENCE, WEBSOCKETS, SYS_TREE, MEMORY_TRACKING) that its CMake files do
    not expose. Adjacent ``#`` comments are used as descriptions.
    """
    project = Path(project_path)
    candidates = [project / "config.mk", project / "Makefile"]
    files = [path for path in candidates if path.is_file()]

    if not files:
        return []

    features: dict[str, Feature] = {}
    assignment_re = re.compile(
        r"^\s*(WITH_[A-Za-z0-9_]+)\s*[?:+]?=\s*(yes|no|ON|OFF|1|0)\s*$",
        re.IGNORECASE,
    )

    for path in files:
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue

        for index, line in enumerate(lines):
            match = assignment_re.match(line)
            if not match:
                continue

            raw_name = match.group(1).upper()
            value = match.group(2).lower()

            if raw_name in features:
                continue

            features[raw_name] = Feature(
                name=raw_name,
                raw_name=raw_name,
                description=_preceding_comment(lines, index),
                default_enabled=value in ("yes", "on", "1"),
                source="make",
            )

    return sorted(features.values(), key=lambda item: item.name)


def _preceding_comment(lines: list[str], index: int) -> str | None:
    """Collect the contiguous comment block immediately above a line."""
    collected: list[str] = []
    cursor = index - 1

    while cursor >= 0:
        stripped = lines[cursor].strip()
        if not stripped.startswith("#"):
            break
        text = stripped.lstrip("#").strip()
        if text:
            collected.append(text)
        cursor -= 1

    if not collected:
        return None

    return re.sub(r"\s+", " ", " ".join(reversed(collected)))[:300]


def print_features(features: list[Feature], project_name: str = "Project") -> None:
    """Print discovered features in a readable format."""
    if not features:
        print(f"[!] No features discovered for {project_name}")
        return

    print(f"\n[+] Discovered {len(features)} feature(s) in {project_name}:")
    print("-" * 70)

    for feature in features:
        print(f"\n  Feature: {feature.name}")
        if feature.raw_name and feature.raw_name != feature.name:
            print(f"    Build option: {feature.raw_name}")
        if feature.source:
            print(f"    Found via: {feature.source}")
        if feature.description:
            print(f"    Description: {feature.description}")
        if feature.default_enabled is not None:
            state = "enabled" if feature.default_enabled else "disabled"
            print(f"    Default: {state}")

    print("-" * 70)
