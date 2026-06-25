"""
Report generation module for PRAT.

Generates self-contained HTML reports, DOT graphs, and JSON output
for feature extraction results. No external CDN dependencies.

The interactive HTML report's UI (markup, styling, and behavior) lives in the
``prat.web`` subpackage as a standalone template asset. See
``src/prat/web/README.md`` for the full UI documentation, data contract, and
the ``__PRAT_*__`` placeholder reference used below.
"""

import html
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone

from .extraction import ExtractionResult
from .web import load_report_template


def _embed_json(value: object) -> str:
    """Serialize ``value`` for safe embedding inside an inline <script> block.

    The ``</`` escaping prevents a ``</script>`` sequence appearing in data
    (file names, source snippets) from prematurely closing the script element.
    """
    return json.dumps(value).replace("</", "<\\/")


def generate_html_report(
    extraction_result: ExtractionResult,
    feature: str,
    output_path: str = "report.html",
) -> str:
    """
    Generate a self-contained, interactive HTML report.

    The report bundles summary cards, an SVG impact graph, a sortable and
    filterable results table, an inline source-preview drawer, dark mode,
    CSV/JSON exports, copy actions, and full keyboard navigation — all in a
    single offline document. The UI template ships in :mod:`prat.web`.
    """
    print(f"[+] Generating HTML report: {output_path}")

    sorted_files = sorted(
        extraction_result.file_line_counts.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    total = extraction_result.total_removable_lines
    file_count = len(sorted_files)
    max_lines = max((count for _, count in sorted_files), default=0)
    avg_lines = round(total / file_count) if file_count else 0
    largest_file = sorted_files[0][0] if sorted_files else "n/a"

    file_data = []
    for file_name, count in sorted_files:
        line_numbers = extraction_result.file_line_numbers.get(file_name, [])
        line_content = extraction_result.file_line_content.get(file_name, [])
        snippets = []
        for idx, content in enumerate(line_content):
            line_number = line_numbers[idx] if idx < len(line_numbers) else None
            snippets.append({
                "line_number": line_number,
                "content": content,
            })

        file_data.append({
            "file": file_name,
            "removable_lines": count,
            "line_numbers": line_numbers,
            "snippets": snippets,
        })

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    meta = {
        "feature": feature,
        "total_lines": total,
        "file_count": file_count,
        "avg_lines": avg_lines,
        "max_lines": max_lines,
        "largest_file": largest_file,
        "generated_at": generated_at,
    }

    replacements = {
        "__PRAT_FEATURE__": html.escape(feature),
        "__PRAT_FILE_COUNT__": str(file_count),
        "__PRAT_TOTAL_LINES__": str(total),
        "__PRAT_AVG_LINES__": str(avg_lines),
        "__PRAT_MAX_LINES__": str(max_lines),
        "__PRAT_LARGEST_FILE__": html.escape(largest_file),
        "__PRAT_GENERATED_AT__": html.escape(generated_at),
        "__PRAT_FEATURE_JSON__": _embed_json(feature),
        "__PRAT_FILE_DATA_JSON__": _embed_json(file_data),
        "__PRAT_META_JSON__": _embed_json(meta),
    }

    html_report = load_report_template()
    for token, value in replacements.items():
        html_report = html_report.replace(token, value)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html_report)

    print(f"[+] HTML report generated: {output_path}")
    return output_path


def generate_dot_graph(
    extraction_result: ExtractionResult,
    feature: str = "Feature",
    output_path: str = "FDG.dot",
    max_content_length: int = 80,
) -> str:
    """
    Generate a DOT file showing files and their removable code.

    The graph is fully project-agnostic.
    """
    print(f"[+] Generating DOT graph: {output_path}")

    lines = [
        'digraph PRAT {',
        '  graph [fontsize=10 fontname="Helvetica" label='
        f'"Feature: {feature}\\nRemovable Lines: '
        f'{extraction_result.total_removable_lines}" labelloc=t];',
        '  node [fontsize=9 fontname="Helvetica" shape=box '
        'style="rounded,filled" fillcolor="#e8eaf6"];',
        '  edge [color="#78909c"];',
        '',
        f'  "{feature}" [shape=ellipse fillcolor="#c5cae9" '
        f'fontsize=11 fontname="Helvetica Bold"];',
        '',
    ]

    for file_name, count in sorted(
        extraction_result.file_line_counts.items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        width = max(1.2, min(3.5, count / 50))
        lines.append(
            f'  "{file_name}" [label="{file_name}\\n{count} lines" '
            f'width={width:.1f}];'
        )
        lines.append(f'  "{feature}" -> "{file_name}";')

        content_list = extraction_result.file_line_content.get(file_name, [])
        if content_list and len(content_list) <= 5:
            snippet = "\\n".join(
                content[:max_content_length].replace('"', '\\"')
                for content in content_list[:5]
            )
            snippet_id = f"{file_name}_code"
            lines.append(
                f'  "{snippet_id}" [label="{snippet}" shape=note '
                f'fontsize=7 fillcolor="#fff9c4"];'
            )
            lines.append(f'  "{file_name}" -> "{snippet_id}" [style=dashed];')

    lines.append("}")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"[+] DOT graph generated: {output_path}")
    return output_path


def generate_html_diffs(diff_dir: str, reports_dir: str = "reports") -> bool:
    """
    Generate HTML-formatted diff files using pygmentize.
    """
    if not shutil.which("pygmentize"):
        print("[-] pygmentize not available — skipping per-file HTML diffs")
        return False

    print("[+] Generating per-file HTML diffs...")
    os.makedirs(reports_dir, exist_ok=True)

    success = True
    for diff_file in os.listdir(diff_dir):
        if not os.path.isfile(os.path.join(diff_dir, diff_file)):
            continue

        input_path = os.path.join(diff_dir, diff_file)
        output_file = os.path.join(reports_dir, diff_file + "-diff.html")

        try:
            subprocess.run(
                [
                    "pygmentize", "-l", "diff", "-f", "html",
                    "-O", "full", "-o", output_file, input_path,
                ],
                check=True,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as e:
            print(f"[-] Error generating HTML for {diff_file}: {e}")
            success = False

    return success


def generate_json_report(
    extraction_result: ExtractionResult,
    feature: str,
    output_path: str = "report.json",
) -> str:
    """
    Generate a machine-readable JSON report.
    """
    print(f"[+] Generating JSON report: {output_path}")

    report: dict = {
        "feature": feature,
        "total_removable_lines": extraction_result.total_removable_lines,
        "files_affected": len(extraction_result.file_line_counts),
        "files": [],
    }

    for file_name, count in sorted(
        extraction_result.file_line_counts.items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        entry: dict = {
            "file": file_name,
            "removable_lines": count,
            "line_numbers": extraction_result.file_line_numbers.get(file_name, []),
            "source_snippets": extraction_result.file_line_content.get(file_name, []),
        }
        report["files"].append(entry)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"[+] JSON report generated: {output_path}")
    return output_path
