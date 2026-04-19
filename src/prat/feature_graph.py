"""
Feature graph module for PRAT.

Paper §6: Feature graphs represent the relationship between program features,
source files, and shared code dependencies. They serve as an interactive
decision-support tool for the analyst selecting features for removal.

This module builds the graph data structure from batch analysis results
and generates a self-contained interactive HTML visualization.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

from .extraction import ExtractionResult


@dataclass
class GraphNode:
    """A node in the feature graph."""
    id: str
    label: str
    node_type: str  # "feature" | "file" | "snippet"
    size: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    """An edge in the feature graph."""
    source: str
    target: str
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FeatureGraph:
    """Complete feature graph for a project."""
    project: str
    nodes: List[GraphNode] = field(default_factory=list)
    edges: List[GraphEdge] = field(default_factory=list)
    features: List[str] = field(default_factory=list)
    total_removable_lines: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for JSON/HTML embedding."""
        return {
            "project": self.project,
            "total_removable_lines": self.total_removable_lines,
            "features": self.features,
            "nodes": [
                {
                    "id": n.id,
                    "label": n.label,
                    "type": n.node_type,
                    "size": n.size,
                    **n.metadata,
                }
                for n in self.nodes
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "weight": e.weight,
                    **e.metadata,
                }
                for e in self.edges
            ],
        }

    def to_json(self, output_path: str) -> str:
        """Write graph to JSON file."""
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        return output_path


def build_feature_graph(batch_result: "BatchResult") -> FeatureGraph:
    """
    Build a feature graph from batch analysis results.

    Creates nodes for each feature and each affected source file,
    with edges connecting features to the files they affect.
    Shared files (affected by multiple features) are highlighted.

    Args:
        batch_result: Results from run_batch_analysis()

    Returns:
        FeatureGraph ready for visualization
    """
    graph = FeatureGraph(
        project=batch_result.project,
        total_removable_lines=batch_result.total_removable_lines,
    )

    # Track all files and their feature associations
    file_features: Dict[str, Set[str]] = {}  # file -> set of features
    file_lines: Dict[str, Dict[str, int]] = {}  # file -> {feature: lines}

    for feat_name, fa in batch_result.feature_results.items():
        if not fa.workflow_result or not fa.workflow_result.success:
            continue

        graph.features.append(feat_name)
        ext = fa.workflow_result.extraction_result

        # Feature node
        graph.nodes.append(GraphNode(
            id=f"feat_{feat_name}",
            label=feat_name,
            node_type="feature",
            size=max(1.0, fa.removable_lines / 50),
            metadata={
                "removable_lines": fa.removable_lines,
                "file_count": len(fa.affected_files),
                "description": fa.feature.description or "",
            },
        ))

        # Track file associations
        if ext:
            for file_name, count in ext.file_line_counts.items():
                if file_name not in file_features:
                    file_features[file_name] = set()
                    file_lines[file_name] = {}
                file_features[file_name].add(feat_name)
                file_lines[file_name][feat_name] = count

    # File nodes
    for file_name, features in file_features.items():
        total_lines = sum(file_lines[file_name].values())
        shared = len(features) > 1

        graph.nodes.append(GraphNode(
            id=f"file_{file_name}",
            label=file_name,
            node_type="file",
            size=max(0.5, total_lines / 30),
            metadata={
                "total_lines": total_lines,
                "shared": shared,
                "feature_count": len(features),
                "features": sorted(features),
                "per_feature_lines": file_lines[file_name],
            },
        ))

        # Edges from each feature to this file
        for feat_name in features:
            lines = file_lines[file_name].get(feat_name, 0)
            graph.edges.append(GraphEdge(
                source=f"feat_{feat_name}",
                target=f"file_{file_name}",
                weight=lines,
                metadata={"lines": lines},
            ))

    return graph


def build_feature_graph_from_single(
    extraction_result: ExtractionResult,
    feature: str,
    project: str = "project",
) -> FeatureGraph:
    """
    Build a feature graph from a single-feature analysis.

    Simpler version for when batch mode wasn't used.

    Args:
        extraction_result: Results from extract_features()
        feature: Feature name
        project: Project name for labeling

    Returns:
        FeatureGraph for the single feature
    """
    graph = FeatureGraph(
        project=project,
        total_removable_lines=extraction_result.total_removable_lines,
        features=[feature],
    )

    # Feature node
    graph.nodes.append(GraphNode(
        id=f"feat_{feature}",
        label=feature,
        node_type="feature",
        size=max(1.0, extraction_result.total_removable_lines / 50),
        metadata={
            "removable_lines": extraction_result.total_removable_lines,
            "file_count": len(extraction_result.file_line_counts),
        },
    ))

    # File nodes + edges
    for file_name, count in extraction_result.file_line_counts.items():
        graph.nodes.append(GraphNode(
            id=f"file_{file_name}",
            label=file_name,
            node_type="file",
            size=max(0.5, count / 30),
            metadata={"total_lines": count, "shared": False},
        ))

        graph.edges.append(GraphEdge(
            source=f"feat_{feature}",
            target=f"file_{file_name}",
            weight=count,
            metadata={"lines": count},
        ))

    return graph


# ---------------------------------------------------------------------------
# Interactive HTML visualization
# ---------------------------------------------------------------------------

_GRAPH_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PRAT Feature Graph — {project}</title>
<style>
  :root {{
    --bg: #0f1117; --surface: #1a1d27; --surface-hover: #22262f;
    --border: #2a2e3a; --text: #e2e4e9; --text-secondary: #9ca0ab;
    --text-muted: #6b7080; --primary: #6c8cff; --accent: #40c9a2;
    --warning: #ffb347; --danger: #ff6b6b;
    --mono: 'SF Mono','Fira Code','Consolas',monospace;
    --sans: -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  }}
  @media (prefers-color-scheme: light) {{
    :root {{
      --bg: #f5f6f8; --surface: #fff; --surface-hover: #f0f1f4;
      --border: #e0e2e8; --text: #1a1d27; --text-secondary: #555b6e;
      --text-muted: #8b90a0; --primary: #4a6cf7; --accent: #2da882;
      --warning: #e6a030; --danger: #e05555;
    }}
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: var(--sans); background: var(--bg); color: var(--text); display: flex; height: 100vh; overflow: hidden; }}

  /* Sidebar */
  .sidebar {{
    width: 280px; min-width: 280px; background: var(--surface);
    border-right: 1px solid var(--border); display: flex; flex-direction: column;
    overflow-y: auto;
  }}
  .sidebar h1 {{ font-size: 15px; padding: 16px 16px 4px; font-weight: 600; }}
  .sidebar .subtitle {{ font-size: 11px; color: var(--text-muted); padding: 0 16px 12px; }}
  .sidebar .search {{
    margin: 0 12px 8px; padding: 8px 10px; border-radius: 6px;
    border: 1px solid var(--border); background: var(--bg);
    color: var(--text); font-size: 12px; outline: none;
  }}
  .sidebar .search:focus {{ border-color: var(--primary); }}

  .feature-list {{ list-style: none; padding: 0 8px; flex: 1; }}
  .feature-item {{
    display: flex; align-items: center; gap: 8px;
    padding: 8px 10px; border-radius: 6px; cursor: pointer;
    font-size: 12px; margin-bottom: 2px; transition: background .12s;
  }}
  .feature-item:hover {{ background: var(--surface-hover); }}
  .feature-item.active {{ background: var(--primary); color: #fff; }}
  .feature-item .dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
  .feature-item .name {{ flex: 1; font-weight: 500; }}
  .feature-item .count {{ font-family: var(--mono); font-size: 11px; color: var(--text-muted); }}
  .feature-item.active .count {{ color: rgba(255,255,255,.7); }}

  .clear-btn {{
    display: none; margin: 8px 12px; padding: 6px; border-radius: 6px;
    border: 1px solid var(--border); background: var(--surface);
    color: var(--text-secondary); font-size: 11px; cursor: pointer;
    text-align: center;
  }}
  .clear-btn.visible {{ display: block; }}
  .clear-btn:hover {{ background: var(--surface-hover); }}

  .stats {{ padding: 12px 16px; border-top: 1px solid var(--border); font-size: 11px; color: var(--text-muted); }}
  .stats .stat-row {{ display: flex; justify-content: space-between; margin-bottom: 4px; }}
  .stats .stat-val {{ font-family: var(--mono); color: var(--text-secondary); }}

  /* Graph area */
  .graph-area {{ flex: 1; position: relative; overflow: hidden; }}
  svg {{ width: 100%; height: 100%; }}
  .node circle {{ stroke: var(--border); stroke-width: 1.5; cursor: pointer; transition: opacity .2s; }}
  .node text {{ font-size: 10px; fill: var(--text); pointer-events: none; }}
  .link {{ stroke-opacity: 0.4; transition: opacity .2s, stroke-opacity .2s; }}
  .dimmed {{ opacity: 0.08; }}
  .link.dimmed {{ stroke-opacity: 0.03; }}

  /* Tooltip */
  .tooltip {{
    position: absolute; background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 10px 14px; font-size: 12px;
    pointer-events: none; opacity: 0; transition: opacity .15s;
    max-width: 260px; box-shadow: 0 4px 16px rgba(0,0,0,.3);
  }}
  .tooltip.visible {{ opacity: 1; }}
  .tooltip .tt-title {{ font-weight: 600; margin-bottom: 4px; }}
  .tooltip .tt-row {{ display: flex; justify-content: space-between; gap: 12px; color: var(--text-secondary); }}
  .tooltip .tt-val {{ font-family: var(--mono); color: var(--text); }}
</style>
</head>
<body>

<div class="sidebar">
  <h1>Feature Graph</h1>
  <p class="subtitle">{project} — {feature_count} features · {total_lines} removable lines</p>
  <input class="search" type="text" placeholder="Search features or files…" id="search">
  <ul class="feature-list" id="featureList"></ul>
  <div class="clear-btn" id="clearBtn">✕ Clear Selection</div>
  <div class="stats" id="statsPanel"></div>
</div>

<div class="graph-area" id="graphArea">
  <svg id="graphSvg"></svg>
  <div class="tooltip" id="tooltip"></div>
</div>

<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<script>
const GRAPH_DATA = {graph_json};

(function() {{
  const svg = d3.select('#graphSvg');
  const container = document.getElementById('graphArea');
  const tooltip = document.getElementById('tooltip');
  const featureList = document.getElementById('featureList');
  const clearBtn = document.getElementById('clearBtn');
  const searchInput = document.getElementById('search');
  const statsPanel = document.getElementById('statsPanel');

  const W = container.clientWidth;
  const H = container.clientHeight;

  // Color palette for features
  const COLORS = ['#6c8cff','#40c9a2','#ffb347','#ff6b6b','#c084fc',
                  '#38bdf8','#fb923c','#a3e635','#f472b6','#67e8f9',
                  '#fbbf24','#818cf8','#34d399','#f87171','#a78bfa'];

  const featureColors = {{}};
  GRAPH_DATA.features.forEach((f, i) => {{ featureColors[f] = COLORS[i % COLORS.length]; }});

  // Build node/edge maps
  const nodeMap = {{}};
  GRAPH_DATA.nodes.forEach(n => {{ nodeMap[n.id] = n; }});

  // D3 force simulation
  const g = svg.append('g');

  // Zoom
  svg.call(d3.zoom().scaleExtent([0.2, 5]).on('zoom', (e) => g.attr('transform', e.transform)));

  // Helper functions (declared before use)
  function nodeRadius(d) {{
    if (d.type === 'feature') return 18 + Math.min(d.size * 2, 20);
    return 6 + Math.min(d.size * 1.5, 14);
  }}

  function nodeColor(d) {{
    if (d.type === 'feature') return featureColors[d.label] || '#6c8cff';
    if (d.shared) return 'var(--warning)';
    if (d.features && d.features.length > 0) return featureColors[d.features[0]] || 'var(--text-muted)';
    return 'var(--text-muted)';
  }}

  function dragStart(event, d) {{ if (!event.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }}
  function dragging(event, d) {{ d.fx = event.x; d.fy = event.y; }}
  function dragEnd(event, d) {{ if (!event.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }}

  const sim = d3.forceSimulation(GRAPH_DATA.nodes)
    .force('link', d3.forceLink(GRAPH_DATA.edges).id(d => d.id).distance(d => 80 + 100 / (d.weight + 1)))
    .force('charge', d3.forceManyBody().strength(d => d.type === 'feature' ? -500 : -80))
    .force('center', d3.forceCenter(W / 2, H / 2))
    .force('collision', d3.forceCollide().radius(d => nodeRadius(d) + 6))
    .force('x', d3.forceX(W / 2).strength(0.03))
    .force('y', d3.forceY(H / 2).strength(0.03));

  // Links
  const link = g.selectAll('.link')
    .data(GRAPH_DATA.edges).enter()
    .append('line').attr('class', 'link')
    .attr('stroke', d => {{
      const src = typeof d.source === 'object' ? d.source : nodeMap[d.source];
      return src && src.type === 'feature' ? (featureColors[src.label] || '#6c8cff') : '#555';
    }})
    .attr('stroke-width', d => Math.max(1, Math.min(d.weight / 20, 5)));

  // Nodes
  const node = g.selectAll('.node')
    .data(GRAPH_DATA.nodes).enter()
    .append('g').attr('class', 'node')
    .call(d3.drag().on('start', dragStart).on('drag', dragging).on('end', dragEnd));

  node.append('circle')
    .attr('r', nodeRadius)
    .attr('fill', nodeColor)
    .attr('opacity', d => d.type === 'feature' ? 1 : 0.85);

  node.append('text')
    .text(d => d.label)
    .attr('dx', d => nodeRadius(d) + 4)
    .attr('dy', 3)
    .style('font-weight', d => d.type === 'feature' ? '600' : '400')
    .style('font-size', d => d.type === 'feature' ? '12px' : '10px');

  sim.on('tick', () => {{
    link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
    node.attr('transform', d => `translate(${{d.x}},${{d.y}})`);
  }});

  // --- Interaction ---
  let activeFeature = null;

  function selectFeature(featName) {{
    if (activeFeature === featName) {{ clearSelection(); return; }}
    activeFeature = featName;

    // Highlight sidebar
    featureList.querySelectorAll('.feature-item').forEach(el => {{
      el.classList.toggle('active', el.dataset.feature === featName);
    }});
    clearBtn.classList.add('visible');

    // Find connected nodes
    const featId = `feat_${{featName}}`;
    const connectedIds = new Set([featId]);
    GRAPH_DATA.edges.forEach(e => {{
      const srcId = typeof e.source === 'object' ? e.source.id : e.source;
      const tgtId = typeof e.target === 'object' ? e.target.id : e.target;
      if (srcId === featId) connectedIds.add(tgtId);
      if (tgtId === featId) connectedIds.add(srcId);
    }});

    // Dim everything else
    node.classed('dimmed', d => !connectedIds.has(d.id));
    link.classed('dimmed', d => {{
      const srcId = typeof d.source === 'object' ? d.source.id : d.source;
      return srcId !== featId;
    }});

    updateStats(featName);
  }}

  function clearSelection() {{
    activeFeature = null;
    featureList.querySelectorAll('.feature-item').forEach(el => el.classList.remove('active'));
    clearBtn.classList.remove('visible');
    node.classed('dimmed', false);
    link.classed('dimmed', false);
    updateStats(null);
  }}

  // Sidebar feature list
  GRAPH_DATA.features.forEach(f => {{
    const fa = GRAPH_DATA.nodes.find(n => n.id === `feat_${{f}}`);
    const li = document.createElement('li');
    li.className = 'feature-item';
    li.dataset.feature = f;
    li.innerHTML = `<span class="dot" style="background:${{featureColors[f]}}"></span>`
      + `<span class="name">${{f}}</span>`
      + `<span class="count">${{fa ? fa.removable_lines : 0}} lines</span>`;
    li.onclick = () => selectFeature(f);
    featureList.appendChild(li);
  }});

  clearBtn.onclick = clearSelection;

  // Search
  let searchTimeout;
  searchInput.addEventListener('input', () => {{
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {{
      const q = searchInput.value.toLowerCase();
      featureList.querySelectorAll('.feature-item').forEach(el => {{
        el.style.display = el.textContent.toLowerCase().includes(q) ? '' : 'none';
      }});
      // Also search file nodes
      if (q.length > 1) {{
        node.classed('dimmed', d => {{
          if (!q) return false;
          return !d.label.toLowerCase().includes(q) && !(d.features || []).some(f => f.toLowerCase().includes(q));
        }});
      }} else if (!activeFeature) {{
        node.classed('dimmed', false);
        link.classed('dimmed', false);
      }}
    }}, 300);
  }});

  // Tooltip
  node.on('mouseover', (event, d) => {{
    let html = `<div class="tt-title">${{d.label}}</div>`;
    if (d.type === 'feature') {{
      html += `<div class="tt-row"><span>Removable lines</span><span class="tt-val">${{d.removable_lines}}</span></div>`;
      html += `<div class="tt-row"><span>Files affected</span><span class="tt-val">${{d.file_count}}</span></div>`;
      if (d.description) html += `<div style="margin-top:6px;color:var(--text-muted);font-size:11px">${{d.description}}</div>`;
    }} else {{
      html += `<div class="tt-row"><span>Total lines</span><span class="tt-val">${{d.total_lines}}</span></div>`;
      html += `<div class="tt-row"><span>Shared</span><span class="tt-val">${{d.shared ? 'Yes (' + d.feature_count + ' features)' : 'No'}}</span></div>`;
      if (d.per_feature_lines) {{
        Object.entries(d.per_feature_lines).forEach(([f, n]) => {{
          html += `<div class="tt-row"><span style="color:${{featureColors[f]}}">${{f}}</span><span class="tt-val">${{n}}</span></div>`;
        }});
      }}
    }}
    tooltip.innerHTML = html;
    tooltip.classList.add('visible');
    tooltip.style.left = (event.clientX - container.getBoundingClientRect().left + 12) + 'px';
    tooltip.style.top = (event.clientY - container.getBoundingClientRect().top - 10) + 'px';
  }})
  .on('mousemove', (event) => {{
    tooltip.style.left = (event.clientX - container.getBoundingClientRect().left + 12) + 'px';
    tooltip.style.top = (event.clientY - container.getBoundingClientRect().top - 10) + 'px';
  }})
  .on('mouseout', () => {{ tooltip.classList.remove('visible'); }});

  // Click node to select feature
  node.on('click', (event, d) => {{
    if (d.type === 'feature') selectFeature(d.label);
    else if (d.features && d.features.length === 1) selectFeature(d.features[0]);
  }});

  // Stats panel
  function updateStats(featName) {{
    if (!featName) {{
      const totalFiles = GRAPH_DATA.nodes.filter(n => n.type === 'file').length;
      const sharedFiles = GRAPH_DATA.nodes.filter(n => n.type === 'file' && n.shared).length;
      statsPanel.innerHTML = `
        <div class="stat-row"><span>Total features</span><span class="stat-val">${{GRAPH_DATA.features.length}}</span></div>
        <div class="stat-row"><span>Total files</span><span class="stat-val">${{totalFiles}}</span></div>
        <div class="stat-row"><span>Shared files</span><span class="stat-val">${{sharedFiles}}</span></div>
        <div class="stat-row"><span>Removable lines</span><span class="stat-val">${{GRAPH_DATA.total_removable_lines}}</span></div>`;
    }} else {{
      const fa = GRAPH_DATA.nodes.find(n => n.id === `feat_${{featName}}`);
      if (!fa) return;
      statsPanel.innerHTML = `
        <div class="stat-row"><span>Feature</span><span class="stat-val" style="color:${{featureColors[featName]}}">${{featName}}</span></div>
        <div class="stat-row"><span>Removable lines</span><span class="stat-val">${{fa.removable_lines}}</span></div>
        <div class="stat-row"><span>Files affected</span><span class="stat-val">${{fa.file_count}}</span></div>`;
    }}
  }}
  updateStats(null);

  // Drag handlers defined above (before sim)
}})();
</script>
</body>
</html>
"""


def generate_feature_graph_html(
    graph: FeatureGraph,
    output_path: str = "feature_graph.html",
) -> str:
    """
    Generate an interactive HTML feature graph visualization.

    The visualization is self-contained (only requires D3.js from CDN).
    Features are shown as large colored nodes, source files as smaller nodes,
    with edges weighted by removable line count. Shared files are highlighted.

    Interaction:
    - Click feature in sidebar or graph → isolate its subgraph
    - Search bar filters features and files
    - Hover for detailed tooltips
    - Drag nodes to rearrange
    - Zoom/pan the canvas

    Args:
        graph: FeatureGraph data structure
        output_path: Path to output HTML file

    Returns:
        Path to generated HTML file
    """
    print(f"[+] Generating interactive feature graph: {output_path}")

    graph_json = json.dumps(graph.to_dict())

    html = _GRAPH_HTML_TEMPLATE.format(
        project=graph.project,
        feature_count=len(graph.features),
        total_lines=graph.total_removable_lines,
        graph_json=graph_json,
    )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html)

    print(f"[+] Feature graph generated: {output_path}")
    return output_path
