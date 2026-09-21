"""
gcov parsing for PRAT.

Paper Algorithm 1 defines feature-to-code mapping as a *set difference over
executed lines*:

    L_all = CoverageAnalysis(B_all, T)      # lines executed, all features on
    L_f   = CoverageAnalysis(B_f,   T)      # lines executed, feature f off
    D_f   = L_all \\ L_f

and the paper's Correctness subsection constrains it further:

    "removing only those LOCs that are executed when the relevant feature is
     active, but not when the same feature is disabled. The algorithm does not
     remove LOCs that are never executed regardless of whether the feature is
     active or not."

Computing that requires the *executed* line set of each build, so this module
parses gcov's per-line execution counts rather than diffing gcov text. The three
gcov line states are distinguished because they mean different things to the
algorithm:

    ``      -:   12:...``   no executable code generated for this line (also
                            what an ``#ifdef``-excluded line looks like)
    ``  #####:   12:...``   executable, never executed
    ``      5:   12:...``   executed 5 times

Only the third state contributes to L. Treating ``#####`` as removable would
invert the paper's soundness property, and ``-:`` lines carry no coverage
information at all.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

# gcov emits "<count>:<line>:<source>"; count is right-aligned in a 9-char
# field, line number in a 5-char field, but both widths grow for large files,
# so match leniently rather than by column.
_GCOV_LINE = re.compile(r"^\s*([^:]*?)\s*:\s*(\d+)\s*:(.*)$")

# Counts gcov renders for "executable but never executed". "=====" is used for
# lines excluded by an unexecuted-block filter in some gcov versions.
_NEVER_EXECUTED = ("#####", "=====")

# A gcov count may carry a suffix marker (e.g. "5*" meaning "some blocks on this
# line were not executed"). The numeric prefix is the execution count.
_COUNT_PREFIX = re.compile(r"^(\d+)")

# With ``gcov -f``, per-function summaries are interleaved into the .gcov file:
#     function mosquitto_tls_set called 3 returned 100% blocks executed 86%
# Parsing these gives the function-level coverage the paper's fuzzing table
# reports alongside line coverage.
_GCOV_FUNCTION = re.compile(
    r"^function\s+(?P<name>.+?)\s+called\s+(?P<called>\d+)\s+returned\s+"
    r"(?P<returned>\d+)%\s+blocks executed\s+(?P<blocks>\d+)%"
)


@dataclass
class GcovFile:
    """Parsed coverage for a single source file.

    Attributes:
        source_path: Path recorded in the gcov ``Source:`` header, relative to
            the build root (e.g. ``av1/encoder/rdopt.c``). This is the stable
            identity of the file; basenames collide across directories.
        gcov_path: Path of the ``.gcov`` file this was parsed from.
        executed: Line numbers with an execution count >= 1. This is the L set
            of Algorithm 1.
        never_executed: Line numbers that are executable but were never
            executed (gcov ``#####``). Retained for reporting; the paper's
            algorithm never removes these.
        non_executable: Line numbers gcov attributes no code to (gcov ``-``),
            including preprocessor-excluded regions.
        source: Line number -> source text, for every line gcov listed.
        functions: Function name -> number of times called. Populated only when
            gcov was run with ``-f``; empty otherwise.
    """

    source_path: str
    gcov_path: str
    executed: set[int] = field(default_factory=set)
    never_executed: set[int] = field(default_factory=set)
    non_executable: set[int] = field(default_factory=set)
    source: dict[int, str] = field(default_factory=dict)
    functions: dict[str, int] = field(default_factory=dict)

    @property
    def executable(self) -> set[int]:
        """Lines gcov generated code for, executed or not."""
        return self.executed | self.never_executed

    @property
    def covered_functions(self) -> set[str]:
        """Functions called at least once."""
        return {name for name, called in self.functions.items() if called > 0}

    def line_coverage(self) -> tuple[int, int]:
        """Return ``(covered, total_executable)`` for this file."""
        return len(self.executed), len(self.executable)

    def function_coverage(self) -> tuple[int, int]:
        """Return ``(covered_functions, total_functions)`` for this file."""
        return len(self.covered_functions), len(self.functions)


def parse_gcov(gcov_path: str) -> GcovFile | None:
    """Parse a ``.gcov`` file into executed / never-executed / non-executable sets.

    Returns None if the file cannot be read or contains no gcov-shaped lines,
    so callers can skip malformed or header-only output (gcov emits a
    header-only file when it cannot locate the source).
    """
    if not os.path.isfile(gcov_path):
        return None

    result = GcovFile(source_path="", gcov_path=gcov_path)
    saw_line = False

    try:
        with open(gcov_path, encoding="utf-8", errors="ignore") as handle:
            for raw in handle:
                stripped = raw.rstrip("\n")

                # ``gcov -f`` interleaves per-function summary lines, which do
                # not match the "count:line:source" shape.
                function = _GCOV_FUNCTION.match(stripped.strip())
                if function:
                    result.functions[function.group("name")] = int(
                        function.group("called")
                    )
                    continue

                match = _GCOV_LINE.match(stripped)
                if not match:
                    continue

                count_field, line_field, text = match.groups()
                line_no = int(line_field)

                # Line 0 carries the metadata headers (Source:, Graph:, ...).
                if line_no == 0:
                    key, _, value = text.partition(":")
                    if key == "Source":
                        result.source_path = value.strip()
                    continue

                saw_line = True
                result.source[line_no] = text

                if count_field in _NEVER_EXECUTED:
                    result.never_executed.add(line_no)
                    continue

                prefix = _COUNT_PREFIX.match(count_field)
                if prefix:
                    if int(prefix.group(1)) > 0:
                        result.executed.add(line_no)
                    else:
                        # An explicit 0 count means executable but not executed.
                        result.never_executed.add(line_no)
                else:
                    # "-" and anything else gcov emits for "no code here".
                    result.non_executable.add(line_no)
    except OSError:
        return None

    if not saw_line:
        return None

    if not result.source_path:
        # Fall back to the gcov filename with the .gcov suffix stripped, so a
        # file whose header is missing still gets a usable identity.
        base = os.path.basename(gcov_path)
        result.source_path = base[:-5] if base.endswith(".gcov") else base

    return result


#: Sidecar file holding normalized function records for a coverage directory.
#: Written when the coverage tool reports functions on stdout rather than inside
#: the .gcov files, so the data survives to be read back by
#: :func:`load_coverage_dir`.
FUNCTION_SIDECAR = "prat_functions.tsv"

# llvm-cov's `gcov -f` prints to stdout instead of writing into the .gcov file:
#     Function 'mosquitto_tls_set'
#     Lines executed:86.00% of 50
#     ...
#     File 't.c'
# Functions are listed before the File block they belong to.
_LLVM_FUNCTION = re.compile(r"^Function '(?P<name>.+)'$")
_LLVM_FILE = re.compile(r"^File '(?P<path>.+)'$")
_LLVM_LINES = re.compile(r"^Lines executed:(?P<pct>[\d.]+)% of (?P<total>\d+)$")


def parse_tool_function_output(output: str) -> dict[str, dict[str, int]]:
    """Extract per-file function coverage from a coverage tool's stdout.

    Handles llvm-cov's ``Function '<name>'`` / ``File '<path>'`` blocks. GNU gcov
    writes its function summaries into the ``.gcov`` files instead, where
    :func:`parse_gcov` picks them up directly.

    Returns:
        ``{source_path: {function_name: called}}``, where ``called`` is 1 when
        any line of the function executed and 0 otherwise — llvm-cov reports a
        percentage rather than a call count.
    """
    per_file: dict[str, dict[str, int]] = {}
    pending: dict[str, int] = {}
    current: str | None = None

    for raw in output.splitlines():
        line = raw.strip()

        function = _LLVM_FUNCTION.match(line)
        if function:
            current = function.group("name")
            pending.setdefault(current, 0)
            continue

        lines_match = _LLVM_LINES.match(line)
        if lines_match and current is not None:
            executed = float(lines_match.group("pct")) > 0.0
            pending[current] = 1 if executed else 0
            current = None
            continue

        file_match = _LLVM_FILE.match(line)
        if file_match and pending:
            path = file_match.group("path")
            per_file.setdefault(path, {}).update(pending)
            pending = {}
            current = None

    return per_file


def write_function_sidecar(
    coverage_dir: str,
    per_file: dict[str, dict[str, int]],
) -> str | None:
    """Append function records to a coverage directory's sidecar file."""
    if not per_file or not os.path.isdir(coverage_dir):
        return None

    path = os.path.join(coverage_dir, FUNCTION_SIDECAR)
    try:
        with open(path, "a", encoding="utf-8") as handle:
            for source_path, functions in sorted(per_file.items()):
                for name, called in sorted(functions.items()):
                    handle.write(f"{source_path}\t{name}\t{called}\n")
    except OSError:
        return None
    return path


def read_function_sidecar(coverage_dir: str) -> dict[str, dict[str, int]]:
    """Read function records previously written by :func:`write_function_sidecar`."""
    path = os.path.join(coverage_dir, FUNCTION_SIDECAR)
    per_file: dict[str, dict[str, int]] = {}

    if not os.path.isfile(path):
        return per_file

    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            for raw in handle:
                parts = raw.rstrip("\n").split("\t")
                if len(parts) != 3:
                    continue
                source_path, name, called = parts
                try:
                    count = int(called)
                except ValueError:
                    continue
                bucket = per_file.setdefault(source_path, {})
                bucket[name] = max(bucket.get(name, 0), count)
    except OSError:
        return {}

    return per_file


def load_coverage_dir(coverage_dir: str) -> dict[str, GcovFile]:
    """Parse every gcov file in a directory, keyed by recorded source path.

    Keying on the ``Source:`` header rather than the basename keeps files with
    the same basename in different directories distinct, which matters for
    codebases like libaom and OpenDDS that reuse names across subtrees.
    """
    parsed: dict[str, GcovFile] = {}

    if not os.path.isdir(coverage_dir):
        return parsed

    for name in sorted(os.listdir(coverage_dir)):
        path = os.path.join(coverage_dir, name)
        if not os.path.isfile(path):
            continue

        gcov = parse_gcov(path)
        if gcov is None:
            continue

        existing = parsed.get(gcov.source_path)
        if existing is None:
            parsed[gcov.source_path] = gcov
        else:
            # gcov may emit one file per translation unit that included the
            # same header. Union the executed sets: a line executed in any TU
            # is executed, which is what CoverageAnalysis(B, T) means.
            existing.executed |= gcov.executed
            existing.never_executed |= gcov.never_executed
            existing.non_executable |= gcov.non_executable
            existing.source.update(gcov.source)
            for name, called in gcov.functions.items():
                existing.functions[name] = existing.functions.get(name, 0) + called
            # A line executed in one TU must not stay marked never-executed
            # because another TU did not reach it.
            existing.never_executed -= existing.executed

    # Merge in function records the coverage tool reported on stdout rather than
    # inside the .gcov files (llvm-cov behaves this way; GNU gcov does not).
    sidecar = read_function_sidecar(coverage_dir)
    if sidecar:
        by_basename = {
            os.path.basename(path): gcov for path, gcov in parsed.items()
        }
        for source_path, functions in sidecar.items():
            target = parsed.get(source_path) or by_basename.get(
                os.path.basename(source_path)
            )
            if target is None:
                continue
            for name, called in functions.items():
                target.functions[name] = max(target.functions.get(name, 0), called)

    return parsed


def merge_contiguous(line_numbers: list[int]) -> list[tuple[int, int]]:
    """Group sorted line numbers into contiguous ``(start, end)`` runs.

    Paper, Feature selection: "In practice, contiguous lines of code are merged
    in a single node to limit the complexity of the graph."
    """
    if not line_numbers:
        return []

    ordered = sorted(set(line_numbers))
    runs: list[tuple[int, int]] = []
    start = prev = ordered[0]

    for current in ordered[1:]:
        if current == prev + 1:
            prev = current
            continue
        runs.append((start, prev))
        start = prev = current

    runs.append((start, prev))
    return runs


def format_ranges(line_numbers: list[int]) -> str:
    """Render line numbers as a compact range string, e.g. ``12-18, 44, 91-95``."""
    parts = []
    for start, end in merge_contiguous(line_numbers):
        parts.append(str(start) if start == end else f"{start}-{end}")
    return ", ".join(parts)
