"""
Report generation module for PRAT.

Generates self-contained HTML reports, DOT graphs, and JSON output
for feature extraction results. No external CDN dependencies.
"""

import json
import os
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Dict
from .extraction import ExtractionResult


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PRAT — {feature} Feature Report</title>
<style>
  :root {{
    --bg: #0f1117; --surface: #1a1d27; --surface-hover: #22262f;
    --border: #2a2e3a; --text: #e2e4e9; --text-secondary: #9ca0ab;
    --text-muted: #6b7080; --primary: #6c8cff; --accent: #40c9a2;
    --danger: #ff6b6b; --mono: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    --sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  }}
  @media (prefers-color-scheme: light) {{
    :root {{
      --bg: #f5f6f8; --surface: #ffffff; --surface-hover: #f0f1f4;
      --border: #e0e2e8; --text: #1a1d27; --text-secondary: #555b6e;
      --text-muted: #8b90a0; --primary: #4a6cf7; --accent: #2da882;
      --danger: #e05555;
    }}
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: var(--sans); background: var(--bg); color: var(--text);
    line-height: 1.5; padding: 32px; max-width: 960px; margin: 0 auto;
  }}
  h1 {{ font-size: 22px; font-weight: 600; margin-bottom: 4px; }}
  .subtitle {{ color: var(--text-muted); font-size: 13px; margin-bottom: 24px; }}

  /* Summary cards */
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 24px; }}
  .card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 16px 18px;
  }}
  .card-label {{ font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--text-muted); margin-bottom: 4px; }}
  .card-value {{ font-size: 26px; font-weight: 700; font-family: var(--mono); }}
  .card-value.primary {{ color: var(--primary); }}
  .card-value.accent {{ color: var(--accent); }}

  /* Filter */
  .filter-bar {{ margin-bottom: 16px; }}
  .filter-bar input {{
    width: 100%; padding: 10px 14px; border-radius: 8px;
    border: 1px solid var(--border); background: var(--surface);
    color: var(--text); font-size: 13px; outline: none;
  }}
  .filter-bar input:focus {{ border-color: var(--primary); }}

  /* Table */
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{
    text-align: left; color: var(--text-muted); font-weight: 500;
    padding: 10px 14px; border-bottom: 2px solid var(--border);
    cursor: pointer; user-select: none; white-space: nowrap;
  }}
  th:hover {{ color: var(--text); }}
  th .arrow {{ font-size: 10px; margin-left: 4px; opacity: .4; }}
  th.sorted .arrow {{ opacity: 1; color: var(--primary); }}
  td {{
    padding: 10px 14px; border-bottom: 1px solid var(--border);
    font-family: var(--mono); font-size: 12px;
  }}
  td:first-child {{ font-family: var(--sans); font-size: 13px; color: var(--text); }}
  tr:hover td {{ background: var(--surface-hover); }}
  .bar-cell {{ display: flex; align-items: center; gap: 10px; }}
  .bar {{ height: 6px; border-radius: 3px; background: var(--primary); min-width: 2px; }}
  .total-row td {{ font-weight: 700; border-top: 2px solid var(--border); color: var(--accent); }}

  /* Footer */
  .footer {{ margin-top: 24px; font-size: 11px; color: var(--text-muted); text-align: center; }}
</style>
</head>
<body>
<h1>PRAT Feature Report</h1>
<p class="subtitle">Feature: <strong>{feature}</strong> · {file_count} files · {total_lines} removable lines</p>

<div class="cards">
  <div class="card">
    <div class="card-label">Total Removable Lines</div>
    <div class="card-value primary">{total_lines}</div>
  </div>
  <div class="card">
    <div class="card-label">Files Affected</div>
    <div class="card-value accent">{file_count}</div>
  </div>
  <div class="card">
    <div class="card-label">Avg Lines / File</div>
    <div class="card-value">{avg_lines}</div>
  </div>
  <div class="card">
    <div class="card-label">Largest File</div>
    <div class="card-value">{max_lines}</div>
  </div>
</div>

<div class="filter-bar">
  <input type="text" id="filter" placeholder="Filter files…" autocomplete="off">
</div>

<table id="results">
  <thead>
    <tr>
      <th data-col="0" data-type="string">Source File <span class="arrow">▲</span></th>
      <th data-col="1" data-type="number" class="sorted">Lines to Remove <span class="arrow">▼</span></th>
    </tr>
  </thead>
  <tbody>
{rows}
    <tr class="total-row">
      <td>Total</td>
      <td><div class="bar-cell"><span>{total_lines}</span></div></td>
    </tr>
  </tbody>
</table>

<p class="footer">Generated by PRAT — Protocol Representation and Analysis Toolkit</p>

<script>
(function() {{
  const table = document.getElementById('results');
  const tbody = table.tBodies[0];
  const headers = table.querySelectorAll('th');
  const filter = document.getElementById('filter');
  let sortCol = 1, sortAsc = false;

  function sortTable(col, asc) {{
    const rows = Array.from(tbody.querySelectorAll('tr:not(.total-row)'));
    const type = headers[col].dataset.type;
    rows.sort((a, b) => {{
      let va = a.cells[col].dataset.value || a.cells[col].textContent;
      let vb = b.cells[col].dataset.value || b.cells[col].textContent;
      if (type === 'number') {{ va = +va; vb = +vb; }}
      else {{ va = va.toLowerCase(); vb = vb.toLowerCase(); }}
      return (va < vb ? -1 : va > vb ? 1 : 0) * (asc ? 1 : -1);
    }});
    const total = tbody.querySelector('.total-row');
    rows.forEach(r => tbody.insertBefore(r, total));
  }}

  headers.forEach(th => {{
    th.addEventListener('click', () => {{
      const col = +th.dataset.col;
      if (col === sortCol) sortAsc = !sortAsc; else {{ sortCol = col; sortAsc = true; }}
      headers.forEach(h => {{ h.classList.remove('sorted'); h.querySelector('.arrow').textContent = '▲'; }});
      th.classList.add('sorted');
      th.querySelector('.arrow').textContent = sortAsc ? '▲' : '▼';
      sortTable(sortCol, sortAsc);
    }});
  }});

  filter.addEventListener('input', () => {{
    const q = filter.value.toLowerCase();
    tbody.querySelectorAll('tr:not(.total-row)').forEach(r => {{
      r.style.display = r.cells[0].textContent.toLowerCase().includes(q) ? '' : 'none';
    }});
  }});

  sortTable(sortCol, sortAsc);
}})();
</script>
</body>
</html>
"""


def generate_html_report(
    extraction_result: ExtractionResult,
    feature: str,
    output_path: str = "report.html",
) -> str:
    """
    Generate a modern, self-contained HTML report.

    The report includes summary cards, a sortable/filterable table,
    and inline bar charts. No external CDN dependencies.

    Args:
        extraction_result: Results from feature extraction
        feature: Feature name for report title
        output_path: Path to output HTML file

    Returns:
        Path to generated HTML file
    """
    print(f"[+] Generating HTML report: {output_path}")

    sorted_files = sorted(
        extraction_result.file_line_counts.items(),
        key=lambda x: x[1],
        reverse=True,
    )

    total = extraction_result.total_removable_lines
    file_count = len(sorted_files)
    max_lines = max((c for _, c in sorted_files), default=0)
    avg_lines = round(total / file_count) if file_count else 0

    # Build table rows
    rows = []
    for file_name, count in sorted_files:
        pct = (count / max_lines * 100) if max_lines else 0
        # Link to per-file HTML diff if it exists
        report_name = file_name + ".gcov-diff.html"
        report_dir = Path(output_path).parent / "reports"
        report_file = report_dir / report_name

        if report_file.exists():
            cell = f'<a href="reports/{report_name}" style="color:var(--primary);text-decoration:none">{file_name}</a>'
        else:
            cell = file_name

        rows.append(
            f'    <tr>'
            f'<td>{cell}</td>'
            f'<td data-value="{count}"><div class="bar-cell">'
            f'<span>{count}</span>'
            f'<div class="bar" style="width:{pct:.1f}%"></div>'
            f'</div></td>'
            f'</tr>'
        )

    html = _HTML_TEMPLATE.format(
        feature=feature,
        total_lines=total,
        file_count=file_count,
        avg_lines=avg_lines,
        max_lines=max_lines,
        rows="\n".join(rows),
    )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html)

    print(f"[+] HTML report generated: {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# DOT graph — project-agnostic
# ---------------------------------------------------------------------------

def generate_dot_graph(
    extraction_result: ExtractionResult,
    feature: str = "Feature",
    output_path: str = "FDG.dot",
    max_content_length: int = 80,
) -> str:
    """
    Generate a DOT file showing files and their removable code.

    The graph is fully project-agnostic — no hardcoded component names.

    Args:
        extraction_result: Results from feature extraction
        feature: Feature name for graph title
        output_path: Path to output DOT file
        max_content_length: Max characters for code snippet nodes

    Returns:
        Path to generated DOT file
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
        key=lambda x: x[1],
        reverse=True,
    ):
        # Size the node by line count
        width = max(1.2, min(3.5, count / 50))
        lines.append(
            f'  "{file_name}" [label="{file_name}\\n{count} lines" '
            f'width={width:.1f}];'
        )
        lines.append(f'  "{feature}" -> "{file_name}";')

        # Add code snippet nodes for small files
        content_list = extraction_result.file_line_content.get(file_name, [])
        if content_list and len(content_list) <= 5:
            snippet = "\\n".join(
                s[:max_content_length].replace('"', '\\"')
                for s in content_list[:5]
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


# ---------------------------------------------------------------------------
# HTML diff generation (per-file, requires pygmentize)
# ---------------------------------------------------------------------------

def generate_html_diffs(diff_dir: str, reports_dir: str = "reports") -> bool:
    """
    Generate HTML-formatted diff files using pygmentize.

    Args:
        diff_dir: Directory containing diff files
        reports_dir: Directory to store HTML reports

    Returns:
        True if successful, False otherwise
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


# ---------------------------------------------------------------------------
# JSON report — machine-readable
# ---------------------------------------------------------------------------

def generate_json_report(
    extraction_result: ExtractionResult,
    feature: str,
    output_path: str = "report.json",
) -> str:
    """
    Generate a machine-readable JSON report.

    Args:
        extraction_result: Results from feature extraction
        feature: Feature name
        output_path: Path to output JSON file

    Returns:
        Path to generated JSON file
    """
    print(f"[+] Generating JSON report: {output_path}")

    report: Dict = {
        "feature": feature,
        "total_removable_lines": extraction_result.total_removable_lines,
        "files_affected": len(extraction_result.file_line_counts),
        "files": [],
    }

    for file_name, count in sorted(
        extraction_result.file_line_counts.items(),
        key=lambda x: x[1],
        reverse=True,
    ):
        entry: Dict = {
            "file": file_name,
            "removable_lines": count,
            "line_numbers": extraction_result.file_line_numbers.get(file_name, []),
        }
        report["files"].append(entry)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"[+] JSON report generated: {output_path}")
    return output_path
