"""
Report generation module for PRAT.

Generates self-contained HTML reports, DOT graphs, and JSON output
for feature extraction results. No external CDN dependencies.
"""

import html
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict

from .extraction import ExtractionResult


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PRAT — {feature} Feature Report</title>
<style>
  :root {{
    --bg: #f4efe6;
    --surface: #fffdf8;
    --surface-alt: #f6efe4;
    --surface-hover: #eee3d1;
    --border: #dbcdb5;
    --text: #1f2633;
    --text-secondary: #5c6678;
    --text-muted: #8c95a5;
    --primary: #2f67d8;
    --accent: #157a6e;
    --warning: #c88414;
    --shadow: 0 18px 48px rgba(41, 51, 70, 0.12);
    --mono: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    --sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: var(--sans);
    color: var(--text);
    background:
      radial-gradient(circle at top left, rgba(47,103,216,.08), transparent 28%),
      radial-gradient(circle at top right, rgba(21,122,110,.08), transparent 22%),
      linear-gradient(180deg, #faf5ec 0%, var(--bg) 100%);
    min-height: 100vh;
    padding: 24px;
  }}
  .shell {{
    max-width: 1500px;
    margin: 0 auto;
  }}
  .hero {{
    display: flex;
    justify-content: space-between;
    gap: 16px;
    align-items: end;
    margin-bottom: 18px;
  }}
  .hero h1 {{
    font-size: 30px;
    margin-bottom: 8px;
  }}
  .subtitle {{
    color: var(--text-secondary);
    font-size: 14px;
  }}
  .summary-strip {{
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    border: 1px solid var(--border);
    border-radius: 18px;
    background: rgba(255,253,248,.86);
    box-shadow: var(--shadow);
  }}
  .summary-pill {{
    padding: 8px 12px;
    border-radius: 999px;
    background: var(--surface-alt);
    font-size: 12px;
    color: var(--text-secondary);
  }}
  .summary-pill strong {{
    color: var(--text);
    font-family: var(--mono);
  }}
  .cards {{
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
    margin-bottom: 18px;
  }}
  .card {{
    border: 1px solid var(--border);
    border-radius: 18px;
    background: rgba(255,253,248,.9);
    box-shadow: var(--shadow);
    padding: 16px 18px;
  }}
  .card-label {{
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: var(--text-muted);
    margin-bottom: 6px;
  }}
  .card-value {{
    font-size: 30px;
    font-weight: 700;
    font-family: var(--mono);
  }}
  .card-note {{
    margin-top: 4px;
    color: var(--text-secondary);
    font-size: 12px;
  }}
  .layout {{
    display: grid;
    grid-template-columns: minmax(0, 1.2fr) 420px;
    gap: 16px;
  }}
  .panel {{
    border: 1px solid var(--border);
    border-radius: 22px;
    background: rgba(255,253,248,.92);
    box-shadow: var(--shadow);
    overflow: hidden;
  }}
  .panel-header {{
    padding: 18px 20px 16px;
    border-bottom: 1px solid var(--border);
    background: linear-gradient(180deg, rgba(47,103,216,.08), transparent);
  }}
  .panel-header h2 {{
    font-size: 18px;
    margin-bottom: 6px;
  }}
  .panel-header p {{
    font-size: 13px;
    color: var(--text-secondary);
  }}
  .panel-body {{
    padding: 18px 20px 20px;
  }}
  .graph-toolbar {{
    display: flex;
    gap: 10px;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 14px;
  }}
  .search {{
    width: min(280px, 100%);
    padding: 10px 12px;
    border-radius: 12px;
    border: 1px solid var(--border);
    background: var(--surface-alt);
    color: var(--text);
    font-size: 13px;
    outline: none;
  }}
  .search:focus {{
    border-color: var(--primary);
    box-shadow: 0 0 0 3px rgba(47,103,216,.14);
  }}
  .legend {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    color: var(--text-secondary);
    font-size: 12px;
  }}
  .legend-item {{
    display: flex;
    align-items: center;
    gap: 6px;
  }}
  .legend-swatch {{
    width: 12px;
    height: 12px;
    border-radius: 4px;
  }}
  .graph-frame {{
    border: 1px solid var(--border);
    border-radius: 18px;
    background:
      radial-gradient(circle at center, rgba(47,103,216,.06), transparent 42%),
      linear-gradient(180deg, #fffdfa 0%, #f7efe2 100%);
    padding: 8px;
    margin-bottom: 16px;
  }}
  #graphSvg {{
    width: 100%;
    height: 430px;
    display: block;
  }}
  .node-feature {{
    fill: var(--primary);
  }}
  .node-file {{
    fill: var(--accent);
  }}
  .node-selected {{
    stroke: #ffffff;
    stroke-width: 5;
  }}
  .node-dimmed {{
    opacity: .18;
  }}
  .link {{
    stroke: rgba(47,103,216,.26);
    stroke-width: 2;
  }}
  .link-dimmed {{
    opacity: .12;
  }}
  .graph-label {{
    fill: var(--text);
    font-size: 12px;
    font-weight: 600;
  }}
  .graph-subtle {{
    fill: var(--text-secondary);
    font-size: 11px;
  }}
  .table-shell {{
    border: 1px solid var(--border);
    border-radius: 18px;
    overflow: hidden;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  th {{
    text-align: left;
    padding: 12px 14px;
    background: var(--surface-alt);
    color: var(--text-secondary);
    font-size: 12px;
    cursor: pointer;
    user-select: none;
    border-bottom: 1px solid var(--border);
  }}
  th.sorted {{
    color: var(--primary);
  }}
  td {{
    padding: 12px 14px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }}
  tbody tr {{
    cursor: pointer;
  }}
  tbody tr:hover {{
    background: var(--surface-hover);
  }}
  tbody tr.active {{
    background: rgba(47,103,216,.08);
  }}
  .file-name {{
    font-weight: 600;
  }}
  .file-meta {{
    margin-top: 3px;
    font-size: 11px;
    color: var(--text-secondary);
  }}
  .metric-cell {{
    font-family: var(--mono);
  }}
  .bar-wrap {{
    display: flex;
    align-items: center;
    gap: 10px;
  }}
  .bar {{
    height: 8px;
    min-width: 2px;
    border-radius: 999px;
    background: linear-gradient(90deg, var(--primary), var(--accent));
  }}
  .details-body {{
    padding: 18px 20px 20px;
    max-height: 980px;
    overflow-y: auto;
  }}
  .eyebrow {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: var(--text-muted);
    margin-bottom: 8px;
  }}
  .details-title {{
    font-size: 24px;
    margin-bottom: 6px;
  }}
  .details-subtitle {{
    font-size: 13px;
    color: var(--text-secondary);
    margin-bottom: 16px;
  }}
  .detail-grid {{
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
    margin-bottom: 16px;
  }}
  .detail-card {{
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 12px;
    background: var(--surface-alt);
  }}
  .detail-card-label {{
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: var(--text-muted);
    margin-bottom: 5px;
  }}
  .detail-card-value {{
    font-size: 21px;
    font-weight: 700;
    font-family: var(--mono);
  }}
  .detail-section {{
    margin-bottom: 16px;
  }}
  .detail-section h3 {{
    font-size: 14px;
    margin-bottom: 10px;
  }}
  .insight-list {{
    display: grid;
    gap: 10px;
  }}
  .insight {{
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 12px 14px;
    background: var(--surface);
  }}
  .insight strong {{
    display: block;
    margin-bottom: 4px;
  }}
  details.code-block {{
    border: 1px solid var(--border);
    border-radius: 14px;
    background: #fffefb;
    overflow: hidden;
    margin-bottom: 10px;
  }}
  details.code-block summary {{
    list-style: none;
    cursor: pointer;
    padding: 12px 14px;
    background: var(--surface-alt);
    font-size: 12px;
    color: var(--text-secondary);
    border-bottom: 1px solid transparent;
  }}
  details.code-block[open] summary {{
    border-bottom-color: var(--border);
  }}
  details.code-block summary::-webkit-details-marker {{
    display: none;
  }}
  details.code-block summary::before {{
    content: '▸';
    display: inline-block;
    margin-right: 8px;
    transition: transform .12s;
  }}
  details.code-block[open] summary::before {{
    transform: rotate(90deg);
  }}
  .code-meta {{
    margin-left: 22px;
    font-size: 11px;
    color: var(--text-muted);
  }}
  .code-view {{
    max-height: 320px;
    overflow: auto;
    padding: 10px 0;
  }}
  .code-line {{
    display: grid;
    grid-template-columns: 74px minmax(0, 1fr);
    gap: 12px;
    padding: 2px 14px;
    font-family: var(--mono);
    font-size: 12px;
    line-height: 1.6;
  }}
  .code-line:hover {{
    background: rgba(47,103,216,.05);
  }}
  .line-number {{
    color: var(--text-muted);
    text-align: right;
    user-select: none;
  }}
  .line-content {{
    white-space: pre-wrap;
    word-break: break-word;
  }}
  .empty-state {{
    border: 1px dashed var(--border);
    border-radius: 16px;
    padding: 16px;
    color: var(--text-secondary);
    background: rgba(255,255,255,.5);
  }}
  .footer {{
    margin-top: 16px;
    text-align: center;
    color: var(--text-muted);
    font-size: 11px;
  }}
  @media (max-width: 1200px) {{
    .layout {{
      grid-template-columns: 1fr;
    }}
  }}
  @media (max-width: 900px) {{
    body {{
      padding: 14px;
    }}
    .hero {{
      flex-direction: column;
      align-items: start;
    }}
    .cards {{
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
  }}
</style>
</head>
<body>
<div class="shell">
  <section class="hero">
    <div>
      <h1>PRAT Feature Report</h1>
      <p class="subtitle">
        Feature: <strong>{feature}</strong> · {file_count} files · {total_lines} removable lines
      </p>
    </div>
    <div class="summary-strip">
      <div class="summary-pill">Most impacted file: <strong>{largest_file}</strong></div>
      <div class="summary-pill">Average/file: <strong>{avg_lines}</strong></div>
    </div>
  </section>

  <section class="cards">
    <div class="card">
      <div class="card-label">Total Removable Lines</div>
      <div class="card-value">{total_lines}</div>
      <div class="card-note">Feature-specific dead code candidate volume</div>
    </div>
    <div class="card">
      <div class="card-label">Files Affected</div>
      <div class="card-value">{file_count}</div>
      <div class="card-note">Source files participating in this feature</div>
    </div>
    <div class="card">
      <div class="card-label">Average / File</div>
      <div class="card-value">{avg_lines}</div>
      <div class="card-note">Useful for spotting concentrated vs. diffuse removal</div>
    </div>
    <div class="card">
      <div class="card-label">Largest File Slice</div>
      <div class="card-value">{max_lines}</div>
      <div class="card-note">Single-file maximum removable LoC</div>
    </div>
  </section>

  <section class="layout">
    <div class="panel">
      <div class="panel-header">
        <h2>Interactive File Graph</h2>
        <p>Click nodes or rows to inspect removable source lines inline. This view is self-contained and does not jump to raw HTML diffs.</p>
      </div>
      <div class="panel-body">
        <div class="graph-toolbar">
          <input class="search" id="filter" type="text" placeholder="Filter files…">
          <div class="legend">
            <div class="legend-item"><span class="legend-swatch" style="background: var(--primary)"></span><span>Feature hub</span></div>
            <div class="legend-item"><span class="legend-swatch" style="background: var(--accent)"></span><span>Source file</span></div>
          </div>
        </div>

        <div class="graph-frame">
          <svg id="graphSvg" viewBox="0 0 980 430" preserveAspectRatio="xMidYMid meet"></svg>
        </div>

        <div class="table-shell">
          <table id="results">
            <thead>
              <tr>
                <th data-col="file" data-type="string">Source File</th>
                <th data-col="count" data-type="number" class="sorted">Lines to Remove</th>
                <th data-col="span" data-type="number">Line Span</th>
              </tr>
            </thead>
            <tbody id="resultsBody"></tbody>
          </table>
        </div>
      </div>
    </div>

    <aside class="panel">
      <div class="panel-header">
        <div class="eyebrow">Inspector</div>
        <h2 id="detailsHeading">Feature overview</h2>
        <p id="detailsLead">Select a file from the graph or table to inspect the exact removable lines inline.</p>
      </div>
      <div class="details-body" id="detailsBody"></div>
    </aside>
  </section>

  <p class="footer">Generated by PRAT — Protocol Representation and Analysis Toolkit</p>
</div>

<script>
const FEATURE_NAME = {feature_json};
const FILES = {file_data_json};

(function() {{
  const body = document.getElementById('resultsBody');
  const headers = Array.from(document.querySelectorAll('th'));
  const filterInput = document.getElementById('filter');
  const detailsHeading = document.getElementById('detailsHeading');
  const detailsLead = document.getElementById('detailsLead');
  const detailsBody = document.getElementById('detailsBody');
  const svg = document.getElementById('graphSvg');

  let activeFile = null;
  let sortCol = 'count';
  let sortAsc = false;
  let filterQuery = '';

  function escapeHtml(value) {{
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }}

  function getLineSpan(file) {{
    if (!file.line_numbers.length) return 0;
    return file.line_numbers[file.line_numbers.length - 1] - file.line_numbers[0] + 1;
  }}

  function visibleFiles() {{
    const query = filterQuery.trim().toLowerCase();
    let files = FILES.slice();

    if (query) {{
      files = files.filter(file => file.file.toLowerCase().includes(query));
    }}

    files.sort((a, b) => {{
      let av;
      let bv;
      if (sortCol === 'file') {{
        av = a.file.toLowerCase();
        bv = b.file.toLowerCase();
      }} else if (sortCol === 'span') {{
        av = getLineSpan(a);
        bv = getLineSpan(b);
      }} else {{
        av = a.removable_lines;
        bv = b.removable_lines;
      }}

      if (av < bv) return sortAsc ? -1 : 1;
      if (av > bv) return sortAsc ? 1 : -1;
      return 0;
    }});

    return files;
  }}

  function renderTable() {{
    const files = visibleFiles();
    body.innerHTML = files.map(file => {{
      const span = getLineSpan(file);
      const max = Math.max(...FILES.map(item => item.removable_lines), 1);
      const width = Math.max(4, (file.removable_lines / max) * 100);
      return `
        <tr data-file="${{escapeHtml(file.file)}}" class="${{activeFile === file.file ? 'active' : ''}}">
          <td>
            <div class="file-name">${{escapeHtml(file.file)}}</div>
            <div class="file-meta">${{file.line_numbers.length}} captured source lines</div>
          </td>
          <td class="metric-cell">
            <div class="bar-wrap">
              <span>${{file.removable_lines}}</span>
              <div class="bar" style="width:${{width}}%"></div>
            </div>
          </td>
          <td class="metric-cell">${{span}}</td>
        </tr>`;
    }}).join('');

    Array.from(body.querySelectorAll('tr')).forEach(row => {{
      row.addEventListener('click', () => selectFile(row.dataset.file));
    }});

    headers.forEach(header => {{
      header.classList.toggle('sorted', header.dataset.col === sortCol);
    }});
  }}

  function renderGraph() {{
    const files = visibleFiles();
    const cx = 300;
    const cy = 215;
    const radius = files.length > 1 ? 150 : 0;
    const maxCount = Math.max(...FILES.map(item => item.removable_lines), 1);

    const featureCircle = `
      <circle cx="${{cx}}" cy="${{cy}}" r="48" class="node-feature ${{activeFile ? 'node-dimmed' : 'node-selected'}}"></circle>
      <text x="${{cx}}" y="${{cy - 4}}" text-anchor="middle" class="graph-label">${{escapeHtml(FEATURE_NAME)}}</text>
      <text x="${{cx}}" y="${{cy + 16}}" text-anchor="middle" class="graph-subtle">${{FILES.length}} files</text>`;

    const nodes = files.map((file, index) => {{
      const angle = files.length === 1 ? 0 : (Math.PI * 2 * index) / files.length - (Math.PI / 2);
      const x = cx + Math.cos(angle) * radius + 260;
      const y = cy + Math.sin(angle) * radius;
      const nodeRadius = 18 + ((file.removable_lines / maxCount) * 22);
      const dimmed = activeFile && activeFile !== file.file;
      const selected = activeFile === file.file;
      return {{
        file,
        x,
        y,
        nodeRadius,
        dimmed,
        selected,
      }};
    }});

    const linksMarkup = nodes.map(node => `
      <line x1="${{cx + 48}}" y1="${{cy}}" x2="${{node.x - node.nodeRadius}}" y2="${{node.y}}" class="link ${{node.dimmed ? 'link-dimmed' : ''}}"></line>
    `).join('');

    const nodesMarkup = nodes.map(node => `
      <g data-file="${{escapeHtml(node.file.file)}}" class="${{node.dimmed ? 'node-dimmed' : ''}}">
        <circle cx="${{node.x}}" cy="${{node.y}}" r="${{node.nodeRadius}}" class="node-file ${{node.selected ? 'node-selected' : ''}}"></circle>
        <text x="${{node.x}}" y="${{node.y - 4}}" text-anchor="middle" class="graph-label">${{escapeHtml(node.file.file)}}</text>
        <text x="${{node.x}}" y="${{node.y + 16}}" text-anchor="middle" class="graph-subtle">${{node.file.removable_lines}} LoC</text>
      </g>
    `).join('');

    svg.innerHTML = `
      <rect x="0" y="0" width="980" height="430" fill="transparent"></rect>
      ${{featureCircle}}
      ${{linksMarkup}}
      ${{nodesMarkup}}
    `;

    Array.from(svg.querySelectorAll('g[data-file]')).forEach(group => {{
      group.style.cursor = 'pointer';
      group.addEventListener('click', () => selectFile(group.dataset.file));
    }});
  }}

  function renderOverview() {{
    const topFiles = FILES.slice().sort((a, b) => b.removable_lines - a.removable_lines).slice(0, 4);

    detailsHeading.textContent = 'Feature overview';
    detailsLead.textContent = 'Select a file from the graph or table to inspect the exact removable lines inline.';
    detailsBody.innerHTML = `
      <div class="detail-grid">
        <div class="detail-card">
          <div class="detail-card-label">Feature</div>
          <div class="detail-card-value">${{escapeHtml(FEATURE_NAME)}}</div>
        </div>
        <div class="detail-card">
          <div class="detail-card-label">Files affected</div>
          <div class="detail-card-value">${{FILES.length}}</div>
        </div>
      </div>
      <div class="detail-section">
        <h3>Highest-impact files</h3>
        <div class="insight-list">
          ${{
            topFiles.map(file => `
              <div class="insight">
                <strong>${{escapeHtml(file.file)}}</strong>
                <span>${{file.removable_lines}} removable lines · span ${{getLineSpan(file)}} source lines</span>
              </div>
            `).join('')
          }}
        </div>
      </div>
      <div class="detail-section">
        <h3>What changed here</h3>
        <div class="insight-list">
          <div class="insight">
            <strong>Interactive graph</strong>
            <span>The feature sits at the center, with impacted source files sized by removable LoC.</span>
          </div>
          <div class="insight">
            <strong>Inline source inspection</strong>
            <span>Every file now exposes expandable source LoC blocks directly in this report.</span>
          </div>
        </div>
      </div>`;
  }}

  function renderFileDetails(file) {{
    detailsHeading.textContent = file.file;
    detailsLead.textContent = `${{file.removable_lines}} removable lines across ${{file.line_numbers.length}} captured source entries.`;

    const firstLine = file.line_numbers.length ? file.line_numbers[0] : 'n/a';
    const lastLine = file.line_numbers.length ? file.line_numbers[file.line_numbers.length - 1] : 'n/a';

    detailsBody.innerHTML = `
      <div class="detail-grid">
        <div class="detail-card">
          <div class="detail-card-label">Removable LoC</div>
          <div class="detail-card-value">${{file.removable_lines}}</div>
        </div>
        <div class="detail-card">
          <div class="detail-card-label">Line range</div>
          <div class="detail-card-value">${{firstLine}}-${{lastLine}}</div>
        </div>
      </div>
      <div class="detail-section">
        <h3>Source LoC</h3>
        ${{
          file.snippets.length
            ? `
              <details class="code-block" open>
                <summary>Source LoC</summary>
                <div class="code-meta">Expandable inline source snippet for ${{escapeHtml(file.file)}}</div>
                <div class="code-view">
                  ${{
                    file.snippets.map(line => `
                      <div class="code-line">
                        <span class="line-number">${{line.line_number ?? ''}}</span>
                        <span class="line-content">${{escapeHtml(line.content)}}</span>
                      </div>
                    `).join('')
                  }}
                </div>
              </details>
            `
            : '<div class="empty-state">No captured source lines are available for this file.</div>'
        }}
      </div>`;
  }}

  function selectFile(fileName) {{
    activeFile = fileName;
    const file = FILES.find(item => item.file === fileName);
    renderTable();
    renderGraph();
    if (file) renderFileDetails(file);
  }}

  headers.forEach(header => {{
    header.addEventListener('click', () => {{
      const col = header.dataset.col;
      if (sortCol === col) {{
        sortAsc = !sortAsc;
      }} else {{
        sortCol = col;
        sortAsc = col === 'file';
      }}
      renderTable();
    }});
  }});

  filterInput.addEventListener('input', () => {{
    filterQuery = filterInput.value;
    if (activeFile && !visibleFiles().some(file => file.file === activeFile)) {{
      activeFile = null;
      renderOverview();
    }}
    renderTable();
    renderGraph();
  }});

  renderTable();
  renderGraph();
  renderOverview();
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
    Generate a self-contained light-mode HTML report with inline inspection.
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

    html_report = _HTML_TEMPLATE.format(
        feature=html.escape(feature),
        feature_json=json.dumps(feature),
        total_lines=total,
        file_count=file_count,
        avg_lines=avg_lines,
        max_lines=max_lines,
        largest_file=html.escape(largest_file),
        file_data_json=json.dumps(file_data).replace("</", "<\\/"),
    )

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

    report: Dict = {
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
        entry: Dict = {
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
