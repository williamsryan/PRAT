"""
Code comparison reports for PRAT.

Paper, Correctness: "we parsed the output of code coverage analysis to generate
code comparison reports which display, side-by-side, the original code and the
code post-debloating, highlighting feature-relevant code. We then manually
inspected these reports to identify inconsistencies."

Two report kinds are produced:

``coverage_comparison``
    Per source file, the feature-enabled and feature-disabled execution state of
    every line side by side, with lines in D_f marked. This is the artifact for
    auditing the *mapping* — whether PRAT attributed the right lines to a
    feature.

``source_comparison``
    Original source against post-removal source, side by side, with removed
    (feature-relevant) lines highlighted. This is the artifact for auditing the
    *removal*.

Note that the authoritative feature-to-code mapping is the set difference in
:mod:`prat.mapping`, not any textual diff. These reports render that mapping for
human review; they never define it.
"""

from __future__ import annotations

import html
import os
from dataclasses import dataclass, field

from .gcov import GcovFile, load_coverage_dir
from .mapping import FeatureMapping


@dataclass
class ComparisonResult:
    """Result of generating code comparison reports."""

    success: bool
    report_dir: str
    coverage_reports: list[str] = field(default_factory=list)
    source_reports: list[str] = field(default_factory=list)
    index_path: str | None = None
    error_message: str | None = None

    @property
    def total_reports(self) -> int:
        return len(self.coverage_reports) + len(self.source_reports)


_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       margin: 0; padding: 24px; background: #fbfbfd; color: #1d1d22; }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 24px 0 8px; font-weight: 600; }
.meta { color: #62626c; font-size: 13px; margin-bottom: 20px; }
table { border-collapse: collapse; width: 100%; font-family: ui-monospace,
        SFMono-Regular, Menlo, monospace; font-size: 12.5px; }
th { text-align: left; background: #f0f0f4; padding: 6px 10px; font-weight: 600;
     border-bottom: 1px solid #d8d8e0; position: sticky; top: 0; }
td { padding: 1px 10px; vertical-align: top; white-space: pre-wrap;
     border-bottom: 1px solid #f2f2f6; }
td.num { text-align: right; color: #90909c; width: 1%; user-select: none; }
td.cnt { text-align: right; width: 1%; color: #62626c; }
tr.feature { background: #fff4e5; }
tr.feature td.num { color: #a15c00; font-weight: 600; }
tr.removed { background: #ffeaea; }
tr.removed td.code { text-decoration: line-through; color: #8a2b2b; }
tr.kept-dead { background: #f4f4f8; }
.legend { font-size: 12.5px; margin: 12px 0 20px; }
.legend span { display: inline-block; padding: 2px 8px; margin-right: 8px;
               border-radius: 4px; }
.sw-feature { background: #fff4e5; }
.sw-removed { background: #ffeaea; }
.sw-dead { background: #f4f4f8; }
a { color: #0a58ca; }
ul { line-height: 1.7; }
"""


def _shell(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html>\n<html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title><style>{_CSS}</style></head>"
        f"<body>{body}</body></html>\n"
    )


def _count_label(gcov: GcovFile | None, line: int) -> str:
    """Render one build's execution state for a line, in gcov's own vocabulary."""
    if gcov is None:
        return "n/a"
    if line in gcov.executed:
        return "exec"
    if line in gcov.never_executed:
        return "#####"
    return "-"


def _safe_name(source_path: str) -> str:
    """Flatten a source path into a filename, keeping directories distinguishable."""
    return source_path.replace(os.sep, "__").replace("/", "__")


def generate_coverage_comparison(
    mapping: FeatureMapping,
    enabled_coverage_dir: str,
    disabled_coverage_dir: str,
    output_dir: str,
) -> list[str]:
    """Write per-file side-by-side coverage comparison reports.

    Each report lists every line of the file with its execution state in the
    feature-enabled and feature-disabled builds, highlighting the lines that
    the mapping attributed to the feature.
    """
    enabled = load_coverage_dir(enabled_coverage_dir)
    disabled = load_coverage_dir(disabled_coverage_dir)

    os.makedirs(output_dir, exist_ok=True)
    written: list[str] = []

    for source_path, file_map in sorted(mapping.files.items()):
        cov_on = enabled.get(source_path)
        cov_off = disabled.get(source_path)
        if cov_on is None:
            continue

        feature_lines = set(file_map.lines)
        dead_lines = set(file_map.never_executed_both)

        rows = []
        for line in sorted(cov_on.source):
            text = html.escape(cov_on.source[line])
            if line in feature_lines:
                cls = ' class="feature"'
            elif line in dead_lines:
                cls = ' class="kept-dead"'
            else:
                cls = ""
            rows.append(
                f"<tr{cls}><td class='num'>{line}</td>"
                f"<td class='cnt'>{_count_label(cov_on, line)}</td>"
                f"<td class='cnt'>{_count_label(cov_off, line)}</td>"
                f"<td class='code'>{text}</td></tr>"
            )

        body = (
            f"<h1>{html.escape(source_path)}</h1>"
            f"<div class='meta'>Feature <strong>{html.escape(mapping.feature)}</strong>"
            f" &middot; {file_map.count} line(s) in D_f"
            f" &middot; lines {html.escape(file_map.range_label)}"
            f"{' &middot; file exists only with the feature enabled' if file_map.feature_only_file else ''}"
            "</div>"
            "<div class='legend'>"
            "<span class='sw-feature'>in D_f — attributed to this feature</span>"
            "<span class='sw-dead'>never executed in either build — retained</span>"
            "</div>"
            "<table><thead><tr><th>Line</th><th>Feature on</th>"
            "<th>Feature off</th><th>Source</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )

        path = os.path.join(output_dir, f"{_safe_name(source_path)}.coverage.html")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(_shell(f"{source_path} — coverage comparison", body))
        written.append(path)

    return written


def generate_source_comparison(
    mapping: FeatureMapping,
    original_root: str,
    debloated_root: str,
    output_dir: str,
) -> list[str]:
    """Write side-by-side original vs. post-removal source reports.

    Args:
        mapping: The feature mapping whose lines were removed.
        original_root: Root of the pre-removal source tree (e.g. the backup
            created by :func:`prat.removal.remove_feature_code`).
        debloated_root: Root of the post-removal source tree.
        output_dir: Directory to write reports into.
    """
    os.makedirs(output_dir, exist_ok=True)
    written: list[str] = []

    for source_path, file_map in sorted(mapping.files.items()):
        original = _read_lines(os.path.join(original_root, source_path))
        debloated = _read_lines(os.path.join(debloated_root, source_path))
        if original is None:
            continue

        removed = set(file_map.lines)
        rows = []
        for idx, original_line in enumerate(original, start=1):
            after = debloated[idx - 1] if debloated and idx <= len(debloated) else ""
            cls = ' class="removed"' if idx in removed else ""
            rows.append(
                f"<tr{cls}><td class='num'>{idx}</td>"
                f"<td class='code'>{html.escape(original_line)}</td>"
                f"<td class='code'>{html.escape(after)}</td></tr>"
            )

        body = (
            f"<h1>{html.escape(source_path)}</h1>"
            f"<div class='meta'>Feature <strong>{html.escape(mapping.feature)}</strong>"
            f" &middot; {file_map.count} line(s) removed"
            f" &middot; lines {html.escape(file_map.range_label)}</div>"
            "<div class='legend'>"
            "<span class='sw-removed'>removed as feature-relevant code</span></div>"
            "<table><thead><tr><th>Line</th><th>Original</th>"
            "<th>Post-debloating</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )

        path = os.path.join(output_dir, f"{_safe_name(source_path)}.source.html")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(_shell(f"{source_path} — source comparison", body))
        written.append(path)

    return written


def _read_lines(path: str) -> list[str] | None:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            return handle.read().splitlines()
    except OSError:
        return None


def generate_comparison_reports(
    mapping: FeatureMapping,
    enabled_coverage_dir: str,
    disabled_coverage_dir: str,
    output_dir: str,
    original_root: str | None = None,
    debloated_root: str | None = None,
) -> ComparisonResult:
    """Generate the paper's code comparison reports plus a browsable index.

    Source-level comparison is produced only when both a pre-removal and a
    post-removal tree are supplied, since it compares them directly.
    """
    try:
        report_dir = os.path.join(output_dir, "comparison_reports")
        os.makedirs(report_dir, exist_ok=True)

        coverage_reports = generate_coverage_comparison(
            mapping, enabled_coverage_dir, disabled_coverage_dir, report_dir
        )

        source_reports: list[str] = []
        if original_root and debloated_root:
            source_reports = generate_source_comparison(
                mapping, original_root, debloated_root, report_dir
            )

        index_path = _write_index(
            mapping, report_dir, coverage_reports, source_reports
        )

        return ComparisonResult(
            success=True,
            report_dir=report_dir,
            coverage_reports=coverage_reports,
            source_reports=source_reports,
            index_path=index_path,
        )

    except OSError as exc:
        return ComparisonResult(
            success=False,
            report_dir="",
            error_message=f"Failed to generate comparison reports: {exc}",
        )


def _write_index(
    mapping: FeatureMapping,
    report_dir: str,
    coverage_reports: list[str],
    source_reports: list[str],
) -> str:
    def links(paths: list[str]) -> str:
        items = []
        for path in paths:
            name = os.path.basename(path)
            items.append(f"<li><a href='{html.escape(name)}'>{html.escape(name)}</a></li>")
        return f"<ul>{''.join(items)}</ul>" if items else "<p>None generated.</p>"

    body = (
        f"<h1>Code comparison reports — {html.escape(mapping.feature)}</h1>"
        f"<div class='meta'>{mapping.total_lines} line(s) in D_f across "
        f"{len(mapping.files)} file(s) &middot; "
        f"{mapping.excluded_never_executed} never-executed line(s) retained</div>"
        "<h2>Coverage comparison (audit the mapping)</h2>"
        f"{links(coverage_reports)}"
        "<h2>Source comparison (audit the removal)</h2>"
        f"{links(source_reports)}"
    )

    index_path = os.path.join(report_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as handle:
        handle.write(_shell(f"Comparison reports — {mapping.feature}", body))
    return index_path
