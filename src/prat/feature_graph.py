"""
Feature graph module for PRAT.

Paper, Feature selection: "A feature graph is a directed acyclic graph (DAG)
F = {V, E}. The set of vertices V includes nodes representing features, source
files, and sets of lines of code ... Informally, this results in a DAG where the
roots are features, intermediate nodes are source files, and leaves are lines
within source files."

The graph is built with all three tiers. Leaves are *sets* of lines: contiguous
runs are merged into one vertex, as the paper specifies, so a feature spanning
lines 12-18 and 44 contributes two leaves rather than eight. Invariants (unique
vertices, tier ordering, acyclicity) are checked by :func:`_validate_graph`
whenever a graph is built.

Its purpose is decision support: the analyst identifies the available features,
assesses how much code each carries, and descends from a feature into the files
and the specific lines implementing it before choosing what to remove.
"""


from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .extraction import ExtractionResult
from .gcov import format_ranges, merge_contiguous
from .web import load_d3_bundle

if TYPE_CHECKING:
    from .batch import BatchResult


@dataclass
class GraphNode:
    """A node in the feature graph."""

    id: str
    label: str
    #: "feature" (root), "file" (intermediate), or "loc" (leaf: a contiguous
    #: run of lines). The tiers must be linked in that order; see
    #: :func:`_validate_graph`.
    node_type: str
    size: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    """An edge in the feature graph."""

    source: str
    target: str
    weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FeatureGraph:
    """Complete feature graph for a project."""

    project: str
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    total_removable_lines: int = 0

    def to_dict(self) -> dict[str, Any]:
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


class GraphValidationError(ValueError):
    """Raised when a built graph violates the paper's DAG invariants."""


def _validate_graph(graph: FeatureGraph) -> None:
    """Check the invariants the paper's definition of a feature graph implies.

    "A feature graph is a directed acyclic graph (DAG) F = {V, E} ... Informally,
    this results in a DAG where the roots are features, intermediate nodes are
    source files, and leaves are lines within source files."

    Checked here: unique vertex ids, every edge endpoint resolvable, no
    self-loops, the feature -> file -> loc tier ordering, and acyclicity. The
    tier ordering makes acyclicity structural, so a cycle indicates a
    construction bug rather than unusual input.
    """
    tier = {"feature": 0, "file": 1, "loc": 2}

    seen: set[str] = set()
    for node in graph.nodes:
        if node.id in seen:
            raise GraphValidationError(f"duplicate vertex id: {node.id}")
        seen.add(node.id)
        if node.node_type not in tier:
            raise GraphValidationError(
                f"unknown node type {node.node_type!r} on {node.id}"
            )

    node_tier = {node.id: tier[node.node_type] for node in graph.nodes}

    for edge in graph.edges:
        if edge.source not in node_tier:
            raise GraphValidationError(f"edge source not a vertex: {edge.source}")
        if edge.target not in node_tier:
            raise GraphValidationError(f"edge target not a vertex: {edge.target}")
        if edge.source == edge.target:
            raise GraphValidationError(f"self-loop on {edge.source}")
        if node_tier[edge.target] != node_tier[edge.source] + 1:
            raise GraphValidationError(
                f"edge {edge.source} -> {edge.target} does not go "
                f"feature -> file -> loc"
            )
        if node_tier[edge.source] == 1:
            features = edge.metadata.get("features")
            if not isinstance(features, list) or not features:
                raise GraphValidationError(
                    f"file -> loc edge {edge.source} -> {edge.target} "
                    "has no feature attribution"
                )

    # Kahn's algorithm: an acyclic graph fully drains.
    indegree = dict.fromkeys(node_tier, 0)
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_tier}
    for edge in graph.edges:
        indegree[edge.target] += 1
        adjacency[edge.source].append(edge.target)

    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    visited = 0
    while queue:
        current = queue.pop()
        visited += 1
        for neighbour in adjacency[current]:
            indegree[neighbour] -= 1
            if indegree[neighbour] == 0:
                queue.append(neighbour)

    if visited != len(node_tier):
        raise GraphValidationError("graph contains a cycle")


def _line_ranges(
    extraction_result: ExtractionResult,
    file_name: str,
) -> list[tuple[int, int]]:
    """Contiguous (start, end) runs of the removable lines in a file."""
    cached = extraction_result.file_line_ranges.get(file_name)
    if cached:
        return cached
    return merge_contiguous(extraction_result.file_line_numbers.get(file_name, []))


def _build_file_detail(
    extraction_result: ExtractionResult,
    file_name: str,
    feature_name: str,
) -> dict[str, Any]:
    """Build UI-friendly detail payload for a file-feature pair."""
    line_numbers = extraction_result.file_line_numbers.get(file_name, [])
    line_content = extraction_result.file_line_content.get(file_name, [])

    snippet_lines = []
    for idx, content in enumerate(line_content):
        line_number = line_numbers[idx] if idx < len(line_numbers) else None
        snippet_lines.append({
            "line_number": line_number,
            "content": content,
        })

    ranges = _line_ranges(extraction_result, file_name)

    return {
        "feature": feature_name,
        "line_count": extraction_result.file_line_counts.get(file_name, 0),
        "line_numbers": line_numbers,
        # Compact range list (e.g. "12-18, 44, 91-95") rather than a first-last
        # span, which would misleadingly bridge the gaps between runs.
        "line_number_preview": format_ranges(line_numbers) if line_numbers else "n/a",
        "line_ranges": [list(item) for item in ranges],
        "snippet_lines": snippet_lines,
    }


def _loc_node_id(file_name: str, start: int, end: int) -> str:
    return f"loc_{file_name}:{start}-{end}"


def _add_loc_nodes(
    graph: FeatureGraph,
    extraction_result: ExtractionResult,
    file_name: str,
    feature_name: str,
    emitted: set[str],
    max_per_file: int | None = None,
) -> None:
    """Add the LOC tier for one file and the (file, loc) edges.

    Paper, Feature selection: "for each line of code of interest l_i, we
    establish an edge (s, l_i). In practice, contiguous lines of code are merged
    in a single node to limit the complexity of the graph." One vertex is
    therefore emitted per contiguous run, not per line.

    Args:
        max_per_file: Optional cap on runs emitted per file, largest first, to
            bound graph size on very large features. None emits every run.
    """
    ranges = _line_ranges(extraction_result, file_name)
    if not ranges:
        return

    line_numbers = extraction_result.file_line_numbers.get(file_name, [])
    line_content = extraction_result.file_line_content.get(file_name, [])
    content_by_line = dict(zip(line_numbers, line_content))

    ordered = sorted(ranges, key=lambda item: item[1] - item[0], reverse=True)
    if max_per_file is not None:
        ordered = ordered[:max_per_file]

    for start, end in sorted(ordered):
        node_id = _loc_node_id(file_name, start, end)
        span = end - start + 1

        if node_id not in emitted:
            emitted.add(node_id)
            snippet = [
                {"line_number": line, "content": content_by_line.get(line, "")}
                for line in range(start, end + 1)
            ]
            graph.nodes.append(
                GraphNode(
                    id=node_id,
                    label=(f"{file_name}:{start}" if span == 1
                           else f"{file_name}:{start}-{end}"),
                    node_type="loc",
                    size=max(0.3, span / 10),
                    metadata={
                        "file": file_name,
                        "start_line": start,
                        "end_line": end,
                        "line_count": span,
                        "features": [feature_name],
                        "snippet_lines": snippet,
                    },
                )
            )
            graph.edges.append(
                GraphEdge(
                    source=f"file_{file_name}",
                    target=node_id,
                    weight=span,
                    metadata={"lines": span, "features": [feature_name]},
                )
            )
        else:
            # A run already emitted for another feature: record the attribution
            # rather than duplicating the vertex, keeping V a set.
            for node in graph.nodes:
                if node.id == node_id:
                    features = node.metadata.setdefault("features", [])
                    if feature_name not in features:
                        features.append(feature_name)
                    break
            for edge in graph.edges:
                if edge.source == f"file_{file_name}" and edge.target == node_id:
                    features = edge.metadata.setdefault("features", [])
                    if feature_name not in features:
                        features.append(feature_name)
                    break


def build_feature_graph(
    batch_result: BatchResult,
    include_loc_nodes: bool = True,
    max_loc_nodes_per_file: int | None = None,
) -> FeatureGraph:
    """
    Build a feature graph from batch analysis results.

    Produces the paper's three tiers: feature vertices as roots, source-file
    vertices as intermediates, and one vertex per contiguous run of removable
    lines as leaves. Files attributed to more than one feature are flagged so
    the analyst can see shared code before removing anything.

    Args:
        batch_result: Result of :func:`prat.batch.run_batch_analysis`.
        include_loc_nodes: Emit the LOC tier. Disable for a features-to-files
            overview of a very large codebase.
        max_loc_nodes_per_file: Cap LOC vertices per file, largest runs first.
    """
    graph = FeatureGraph(
        project=batch_result.project,
        total_removable_lines=batch_result.total_removable_lines,
    )

    file_features: dict[str, set[str]] = {}
    file_lines: dict[str, dict[str, int]] = {}
    file_details: dict[str, list[dict[str, Any]]] = {}
    extractions: dict[str, ExtractionResult] = {}

    for feat_name, feature_analysis in batch_result.feature_results.items():
        extraction_result = feature_analysis.extraction
        if extraction_result is None or not feature_analysis.analyzed:
            continue

        extractions[feat_name] = extraction_result
        graph.features.append(feat_name)

        graph.nodes.append(
            GraphNode(
                id=f"feat_{feat_name}",
                label=feat_name,
                node_type="feature",
                size=max(1.0, feature_analysis.removable_lines / 50),
                metadata={
                    "removable_lines": feature_analysis.removable_lines,
                    "file_count": len(feature_analysis.affected_files),
                    "description": feature_analysis.feature.description or "",
                },
            )
        )

        for file_name, count in extraction_result.file_line_counts.items():
            if file_name not in file_features:
                file_features[file_name] = set()
                file_lines[file_name] = {}
                file_details[file_name] = []

            file_features[file_name].add(feat_name)
            file_lines[file_name][feat_name] = count
            file_details[file_name].append(
                _build_file_detail(extraction_result, file_name, feat_name)
            )

    emitted_loc: set[str] = set()

    for file_name, features in file_features.items():
        total_lines = sum(file_lines[file_name].values())
        shared = len(features) > 1

        graph.nodes.append(
            GraphNode(
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
                    "per_feature_details": sorted(
                        file_details[file_name],
                        key=lambda item: item["line_count"],
                        reverse=True,
                    ),
                },
            )
        )

        for feat_name in sorted(features):
            lines = file_lines[file_name].get(feat_name, 0)
            graph.edges.append(
                GraphEdge(
                    source=f"feat_{feat_name}",
                    target=f"file_{file_name}",
                    weight=lines,
                    metadata={"lines": lines},
                )
            )

            if include_loc_nodes:
                _add_loc_nodes(
                    graph,
                    extractions[feat_name],
                    file_name,
                    feat_name,
                    emitted_loc,
                    max_loc_nodes_per_file,
                )

    _validate_graph(graph)
    return graph


def build_feature_graph_from_single(
    extraction_result: ExtractionResult,
    feature: str,
    project: str = "project",
    include_loc_nodes: bool = True,
    max_loc_nodes_per_file: int | None = None,
) -> FeatureGraph:
    """Build a feature graph from a single-feature analysis."""
    graph = FeatureGraph(
        project=project,
        total_removable_lines=extraction_result.total_removable_lines,
        features=[feature],
    )

    graph.nodes.append(
        GraphNode(
            id=f"feat_{feature}",
            label=feature,
            node_type="feature",
            size=max(1.0, extraction_result.total_removable_lines / 50),
            metadata={
                "removable_lines": extraction_result.total_removable_lines,
                "file_count": len(extraction_result.file_line_counts),
                "description": "",
            },
        )
    )

    emitted_loc: set[str] = set()

    for file_name, count in extraction_result.file_line_counts.items():
        graph.nodes.append(
            GraphNode(
                id=f"file_{file_name}",
                label=file_name,
                node_type="file",
                size=max(0.5, count / 30),
                metadata={
                    "total_lines": count,
                    "shared": False,
                    "feature_count": 1,
                    "features": [feature],
                    "per_feature_lines": {feature: count},
                    "per_feature_details": [
                        _build_file_detail(extraction_result, file_name, feature)
                    ],
                },
            )
        )
        graph.edges.append(
            GraphEdge(
                source=f"feat_{feature}",
                target=f"file_{file_name}",
                weight=count,
                metadata={"lines": count},
            )
        )

        if include_loc_nodes:
            _add_loc_nodes(
                graph,
                extraction_result,
                file_name,
                feature,
                emitted_loc,
                max_loc_nodes_per_file,
            )

    _validate_graph(graph)
    return graph

_GRAPH_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PRAT Feature Graph — {project}</title>
<style>
  :root {{
    --bg: #f4efe6;
    --surface: #fffdf8;
    --surface-alt: #f6efe4;
    --surface-hover: #efe4d2;
    --border: #dccfb8;
    --text: #1f2633;
    --text-secondary: #5b6678;
    --text-muted: #8b94a5;
    --primary: #2f67d8;
    --accent: #157a6e;
    --warning: #d08a12;
    --danger: #c84c3c;
    --shadow: 0 18px 48px rgba(41, 51, 70, 0.12);
    --mono: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    --sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: var(--sans);
    background:
      radial-gradient(circle at top left, rgba(47,103,216,.08), transparent 28%),
      radial-gradient(circle at top right, rgba(21,122,110,.08), transparent 24%),
      linear-gradient(180deg, #faf5ec 0%, var(--bg) 100%);
    color: var(--text);
    min-height: 100vh;
  }}
  .app {{
    display: grid;
    grid-template-columns: 300px minmax(0, 1fr) 420px;
    gap: 16px;
    height: 100vh;
    padding: 18px;
  }}
  .panel {{
    background: rgba(255,253,248,.92);
    border: 1px solid var(--border);
    border-radius: 22px;
    box-shadow: var(--shadow);
    backdrop-filter: blur(12px);
    min-width: 0;
  }}
  .sidebar {{
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }}
  .sidebar-scroll {{
    overflow-y: auto;
    height: 100%;
  }}
  .sidebar h1 {{
    font-size: 22px;
    font-weight: 700;
    padding: 20px 20px 6px;
  }}
  .sidebar .subtitle {{
    padding: 0 20px 14px;
    color: var(--text-secondary);
    font-size: 12px;
  }}
  .overview-cards {{
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
    padding: 0 20px 14px;
  }}
  .overview-card {{
    padding: 12px;
    border: 1px solid var(--border);
    border-radius: 14px;
    background: linear-gradient(180deg, #fffdfa 0%, var(--surface-alt) 100%);
  }}
  .overview-label {{
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: var(--text-muted);
    margin-bottom: 6px;
  }}
  .overview-value {{
    font-size: 24px;
    font-weight: 700;
  }}
  .overview-note {{
    font-size: 11px;
    color: var(--text-secondary);
    margin-top: 4px;
  }}
  .search {{
    width: calc(100% - 40px);
    margin: 0 20px 12px;
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
  .section-title {{
    padding: 2px 20px 8px;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: var(--text-muted);
  }}
  .feature-list {{
    list-style: none;
    padding: 0 14px 14px;
  }}
  .feature-item {{
    display: grid;
    grid-template-columns: 10px minmax(0, 1fr) auto;
    gap: 10px;
    padding: 10px 12px;
    border-radius: 14px;
    margin-bottom: 6px;
    border: 1px solid transparent;
    cursor: pointer;
    transition: background .12s, transform .12s, border-color .12s;
  }}
  .feature-item:hover {{
    background: var(--surface-hover);
    transform: translateX(2px);
  }}
  .feature-item.active {{
    background: rgba(47,103,216,.1);
    border-color: rgba(47,103,216,.22);
  }}
  .feature-item .dot {{
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-top: 5px;
    box-shadow: 0 0 0 3px rgba(255,255,255,.75);
  }}
  .feature-item .name {{
    font-size: 13px;
    font-weight: 600;
  }}
  .feature-item .meta {{
    display: block;
    margin-top: 3px;
    font-size: 11px;
    color: var(--text-secondary);
  }}
  .feature-item .count {{
    font-family: var(--mono);
    font-size: 11px;
    color: var(--text-secondary);
    align-self: start;
  }}
  .clear-btn {{
    display: none;
    margin: 0 20px 16px;
    padding: 10px;
    border-radius: 12px;
    border: 1px solid var(--border);
    background: var(--surface-alt);
    color: var(--text-secondary);
    font-size: 12px;
    cursor: pointer;
    text-align: center;
  }}
  .clear-btn.visible {{ display: block; }}
  .clear-btn:hover {{ background: var(--surface-hover); }}
  .stats {{
    border-top: 1px solid var(--border);
    padding: 16px 20px 20px;
    font-size: 12px;
    color: var(--text-secondary);
  }}
  .stats .stat-row {{
    display: flex;
    justify-content: space-between;
    margin-bottom: 8px;
  }}
  .stats .stat-val {{
    font-family: var(--mono);
  }}
  .graph-shell {{
    position: relative;
    overflow: hidden;
    background:
      radial-gradient(circle at center, rgba(47,103,216,.05), transparent 45%),
      linear-gradient(180deg, #fffdfa 0%, #f8f1e5 100%);
  }}
  .graph-toolbar {{
    position: absolute;
    top: 16px;
    left: 16px;
    right: 16px;
    z-index: 3;
    display: flex;
    justify-content: space-between;
    gap: 12px;
    pointer-events: none;
  }}
  .toolbar-card {{
    pointer-events: auto;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 14px;
    border-radius: 14px;
    border: 1px solid var(--border);
    background: rgba(255,253,248,.88);
    box-shadow: 0 8px 28px rgba(32,38,49,.08);
  }}
  .toolbar-card strong {{
    display: block;
    font-size: 13px;
  }}
  .toolbar-card span {{
    font-size: 11px;
    color: var(--text-secondary);
  }}
  .legend-swatch {{
    width: 12px;
    height: 12px;
    border-radius: 4px;
    flex-shrink: 0;
  }}
  .graph-area {{
    position: absolute;
    inset: 0;
    overflow: hidden;
  }}
  svg {{
    width: 100%;
    height: 100%;
  }}
  .node circle {{
    stroke: rgba(255,255,255,.92);
    stroke-width: 2.4;
    cursor: pointer;
    transition: opacity .2s, stroke-width .2s;
  }}
  .node.selected circle {{
    stroke-width: 4px;
  }}
  .node text {{
    font-size: 11px;
    fill: var(--text);
    pointer-events: none;
    paint-order: stroke;
    stroke: rgba(255,253,248,.9);
    stroke-width: 4px;
  }}
  .link {{
    stroke-opacity: .48;
    transition: opacity .2s, stroke-opacity .2s;
  }}
  .dimmed {{
    opacity: .12;
  }}
  .link.dimmed {{
    stroke-opacity: .06;
  }}
  .tooltip {{
    position: absolute;
    max-width: 320px;
    padding: 10px 14px;
    border-radius: 10px;
    border: 1px solid var(--border);
    background: var(--surface);
    box-shadow: 0 12px 36px rgba(0,0,0,.14);
    font-size: 12px;
    pointer-events: none;
    opacity: 0;
    transition: opacity .15s;
  }}
  .tooltip.visible {{ opacity: 1; }}
  .tooltip .tt-title {{
    font-weight: 700;
    margin-bottom: 6px;
  }}
  .tooltip .tt-row {{
    display: flex;
    justify-content: space-between;
    gap: 12px;
    color: var(--text-secondary);
  }}
  .tooltip .tt-val {{
    font-family: var(--mono);
    color: var(--text);
  }}
  .details {{
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }}
  .details-header {{
    padding: 20px 20px 16px;
    border-bottom: 1px solid var(--border);
    background: linear-gradient(180deg, rgba(47,103,216,.08), transparent);
  }}
  .eyebrow {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: var(--text-muted);
    margin-bottom: 8px;
  }}
  .details h2 {{
    font-size: 22px;
    margin-bottom: 6px;
  }}
  .details-subtitle {{
    font-size: 13px;
    color: var(--text-secondary);
  }}
  .details-body {{
    overflow-y: auto;
    padding: 18px 20px 20px;
  }}
  .detail-grid {{
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
    margin-bottom: 18px;
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
    font-size: 20px;
    font-weight: 700;
  }}
  .detail-section {{
    margin-bottom: 18px;
  }}
  .detail-section h3 {{
    font-size: 14px;
    margin-bottom: 10px;
  }}
  .list-card {{
    border: 1px solid var(--border);
    border-radius: 14px;
    background: var(--surface);
    overflow: hidden;
    margin-bottom: 10px;
  }}
  .list-card-header {{
    display: flex;
    justify-content: space-between;
    gap: 10px;
    padding: 12px 14px;
    background: var(--surface-alt);
    border-bottom: 1px solid var(--border);
  }}
  .list-card-title {{
    font-size: 13px;
    font-weight: 600;
  }}
  .list-card-subtitle {{
    margin-top: 3px;
    font-size: 11px;
    color: var(--text-secondary);
  }}
  .pill {{
    align-self: start;
    padding: 5px 8px;
    border-radius: 999px;
    background: rgba(47,103,216,.1);
    color: var(--primary);
    font-size: 11px;
    font-family: var(--mono);
  }}
  .feature-chip-row {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }}
  .feature-chip {{
    padding: 7px 10px;
    border-radius: 999px;
    color: #fff;
    font-size: 12px;
    font-weight: 600;
  }}
  details.code-block {{
    border-top: 1px solid var(--border);
    background: #fffefb;
  }}
  details.code-block summary {{
    list-style: none;
    cursor: pointer;
    padding: 11px 14px;
    font-size: 12px;
    color: var(--text-secondary);
  }}
  details.code-block summary::-webkit-details-marker {{ display: none; }}
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
    margin-left: 24px;
    font-size: 11px;
    color: var(--text-muted);
  }}
  .code-view {{
    max-height: 280px;
    overflow: auto;
    border-top: 1px solid var(--border);
    background: #fffdf8;
    padding: 10px 0;
  }}
  .code-line {{
    display: grid;
    grid-template-columns: 68px minmax(0, 1fr);
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
    padding: 18px;
    background: rgba(255,255,255,.5);
    color: var(--text-secondary);
  }}
  @media (max-width: 1200px) {{
    .app {{ grid-template-columns: 280px minmax(0, 1fr); }}
    .details {{ grid-column: 1 / -1; min-height: 320px; }}
  }}
  @media (max-width: 840px) {{
    .app {{
      grid-template-columns: 1fr;
      grid-template-rows: auto minmax(420px, 55vh) auto;
      height: auto;
      min-height: 100vh;
    }}
    .graph-shell {{ min-height: 58vh; }}
  }}
</style>
</head>
<body>
<div class="app">
  <aside class="panel sidebar">
    <div class="sidebar-scroll">
      <h1>Feature Graph</h1>
      <p class="subtitle">{project} · light-mode analysis workspace</p>
      <div class="overview-cards">
        <div class="overview-card">
          <div class="overview-label">Features</div>
          <div class="overview-value">{feature_count}</div>
          <div class="overview-note">Toggle one to isolate its subgraph</div>
        </div>
        <div class="overview-card">
          <div class="overview-label">Removable LoC</div>
          <div class="overview-value">{total_lines}</div>
          <div class="overview-note">Across the current project snapshot</div>
        </div>
      </div>
      <input class="search" type="text" placeholder="Search features or files…" id="search">
      <div class="section-title">Feature Explorer</div>
      <ul class="feature-list" id="featureList"></ul>
      <div class="clear-btn" id="clearBtn">Clear selection</div>
      <div class="stats" id="statsPanel"></div>
    </div>
  </aside>

  <section class="panel graph-shell">
    <div class="graph-toolbar">
      <div class="toolbar-card">
        <div class="legend-swatch" style="background: var(--primary)"></div>
        <div><strong>Feature nodes</strong><span>High-level removal candidates</span></div>
      </div>
      <div class="toolbar-card">
        <div class="legend-swatch" style="background: var(--warning)"></div>
        <div><strong>Shared files</strong><span>Files touched by multiple features</span></div>
      </div>
    </div>
    <div class="graph-area" id="graphArea">
      <svg id="graphSvg"></svg>
      <div class="tooltip" id="tooltip"></div>
    </div>
  </section>

  <aside class="panel details">
    <div class="details-header">
      <div class="eyebrow" id="detailsEyebrow">Overview</div>
      <h2 id="detailsTitle">Interactive removal map</h2>
      <p class="details-subtitle" id="detailsSubtitle">
        Select a feature or file node to inspect line counts, sharing risk, and expandable source snippets inline.
      </p>
    </div>
    <div class="details-body" id="detailsBody"></div>
  </aside>
</div>

<script>__PRAT_D3_SOURCE__</script>
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
  const detailsEyebrow = document.getElementById('detailsEyebrow');
  const detailsTitle = document.getElementById('detailsTitle');
  const detailsSubtitle = document.getElementById('detailsSubtitle');
  const detailsBody = document.getElementById('detailsBody');

  const bounds = container.getBoundingClientRect();
  const W = bounds.width || container.clientWidth || 900;
  const H = bounds.height || container.clientHeight || 700;
  const COLORS = ['#2f67d8', '#157a6e', '#d08a12', '#c84c3c', '#8159d6',
                  '#3191d0', '#dd6b3e', '#5b9c4d', '#d1528d', '#0e9baa'];

  const featureColors = {{}};
  GRAPH_DATA.features.forEach((feature, index) => {{
    featureColors[feature] = COLORS[index % COLORS.length];
  }});

  const nodeMap = {{}};
  GRAPH_DATA.nodes.forEach(node => {{
    nodeMap[node.id] = node;
  }});

  const g = svg.append('g');
  svg.call(
    d3.zoom()
      .scaleExtent([0.25, 4])
      .on('zoom', event => g.attr('transform', event.transform))
  );

  function escapeHtml(value) {{
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }}

  function nodeRadius(node) {{
    if (node.type === 'feature') return 22 + Math.min(node.size * 2.2, 26);
    return 10 + Math.min(node.size * 1.6, 18);
  }}

  function nodeColor(node) {{
    if (node.type === 'feature') return featureColors[node.label] || '#2f67d8';
    if (node.shared) return 'var(--warning)';
    if (node.features && node.features.length > 0) {{
      return featureColors[node.features[0]] || 'var(--accent)';
    }}
    return 'var(--accent)';
  }}

  const linkForce = d3.forceLink(GRAPH_DATA.edges)
    .id(node => node.id)
    .distance(edge => {{
      const sourceId = typeof edge.source === 'object' ? edge.source.id : edge.source;
      return sourceId.startsWith('feat_') ? 155 : 100;
    }});

  const simulation = d3.forceSimulation(GRAPH_DATA.nodes)
    .force('link', linkForce)
    .force('charge', d3.forceManyBody().strength(node => node.type === 'feature' ? -980 : -230))
    .force('center', d3.forceCenter(W / 2, H / 2))
    .force('collision', d3.forceCollide().radius(node => nodeRadius(node) + 10))
    .force('x', d3.forceX(node => node.type === 'feature' ? W * 0.38 : W * 0.58).strength(0.08))
    .force('y', d3.forceY(H / 2).strength(0.045));

  const link = g.selectAll('.link')
    .data(GRAPH_DATA.edges)
    .enter()
    .append('line')
    .attr('class', 'link')
    .attr('stroke', edge => {{
      const source = typeof edge.source === 'object' ? edge.source : nodeMap[edge.source];
      return source && source.type === 'feature' ? (featureColors[source.label] || '#2f67d8') : '#9aa4b6';
    }})
    .attr('stroke-width', edge => Math.max(1.5, Math.min(edge.weight / 16, 7)));

  const node = g.selectAll('.node')
    .data(GRAPH_DATA.nodes)
    .enter()
    .append('g')
    .attr('class', 'node');

  node.append('circle')
    .attr('r', nodeRadius)
    .attr('fill', nodeColor)
    .attr('opacity', item => item.type === 'feature' ? 1 : 0.88);

  node.append('text')
    .text(item => item.label)
    .attr('dx', item => nodeRadius(item) + 6)
    .attr('dy', 3)
    .style('font-weight', item => item.type === 'feature' ? '700' : '500')
    .style('font-size', item => item.type === 'feature' ? '13px' : '11px');

  function dragStarted(event, dragged) {{
    if (!event.active) simulation.alphaTarget(0.3).restart();
    dragged.fx = dragged.x;
    dragged.fy = dragged.y;
  }}

  function dragged(event, dragged) {{
    dragged.fx = event.x;
    dragged.fy = event.y;
  }}

  function dragEnded(event, dragged) {{
    if (!event.active) simulation.alphaTarget(0);
    dragged.fx = null;
    dragged.fy = null;
  }}

  node.call(d3.drag().on('start', dragStarted).on('drag', dragged).on('end', dragEnded));

  simulation.on('tick', () => {{
    link
      .attr('x1', edge => edge.source.x)
      .attr('y1', edge => edge.source.y)
      .attr('x2', edge => edge.target.x)
      .attr('y2', edge => edge.target.y);
    node.attr('transform', item => `translate(${{item.x}},${{item.y}})`);
  }});

  let activeFeature = null;
  let activeNodeId = null;

  function formatFeatureChip(feature) {{
    return `<span class="feature-chip" style="background:${{featureColors[feature] || 'var(--primary)'}}">${{escapeHtml(feature)}}</span>`;
  }}

  function renderOverview() {{
    const fileNodes = GRAPH_DATA.nodes.filter(item => item.type === 'file');
    const sharedFiles = fileNodes
      .filter(item => item.shared)
      .sort((a, b) => b.total_lines - a.total_lines)
      .slice(0, 6);
    const busiestFeatures = GRAPH_DATA.nodes
      .filter(item => item.type === 'feature')
      .sort((a, b) => b.removable_lines - a.removable_lines)
      .slice(0, 4);

    detailsEyebrow.textContent = 'Overview';
    detailsTitle.textContent = 'Interactive removal map';
    detailsSubtitle.textContent = 'Select a feature or file node to inspect line counts, sharing risk, and expandable source snippets inline.';
    detailsBody.innerHTML = `
      <div class="detail-grid">
        <div class="detail-card">
          <div class="detail-card-label">Total files</div>
          <div class="detail-card-value">${{fileNodes.length}}</div>
        </div>
        <div class="detail-card">
          <div class="detail-card-label">Shared files</div>
          <div class="detail-card-value">${{fileNodes.filter(item => item.shared).length}}</div>
        </div>
      </div>
      <div class="detail-section">
        <h3>Highest-impact features</h3>
        ${{
          busiestFeatures.map(item => `
            <div class="list-card">
              <div class="list-card-header">
                <div>
                  <div class="list-card-title">${{escapeHtml(item.label)}}</div>
                  <div class="list-card-subtitle">${{escapeHtml(item.description || 'No feature description available')}}</div>
                </div>
                <div class="pill">${{item.removable_lines}} LoC</div>
              </div>
            </div>
          `).join('') || '<div class="empty-state">No successful feature analyses available yet.</div>'
        }}
      </div>
      <div class="detail-section">
        <h3>Shared files worth reviewing first</h3>
        ${{
          sharedFiles.map(item => `
            <div class="list-card">
              <div class="list-card-header">
                <div>
                  <div class="list-card-title">${{escapeHtml(item.label)}}</div>
                  <div class="list-card-subtitle">${{item.feature_count}} features share this file</div>
                </div>
                <div class="pill">${{item.total_lines}} LoC</div>
              </div>
            </div>
          `).join('') || '<div class="empty-state">No shared files detected. Each file currently maps to a single feature.</div>'
        }}
      </div>`;
  }}

  function renderFeatureDetails(featureName) {{
    const featureNode = GRAPH_DATA.nodes.find(item => item.id === `feat_${{featureName}}`);
    if (!featureNode) return;

    const connectedFiles = GRAPH_DATA.nodes
      .filter(item => item.type === 'file' && (item.features || []).includes(featureName))
      .sort((a, b) => (b.per_feature_lines?.[featureName] || 0) - (a.per_feature_lines?.[featureName] || 0));

    detailsEyebrow.textContent = 'Feature';
    detailsTitle.textContent = featureNode.label;
    detailsSubtitle.textContent = featureNode.description || 'Feature-level removal candidate summary';
    detailsBody.innerHTML = `
      <div class="detail-grid">
        <div class="detail-card">
          <div class="detail-card-label">Removable LoC</div>
          <div class="detail-card-value">${{featureNode.removable_lines || 0}}</div>
        </div>
        <div class="detail-card">
          <div class="detail-card-label">Files affected</div>
          <div class="detail-card-value">${{featureNode.file_count || connectedFiles.length}}</div>
        </div>
      </div>
      <div class="detail-section">
        <h3>Files in this subgraph</h3>
        ${{
          connectedFiles.map(fileNode => {{
            const detail = (fileNode.per_feature_details || []).find(item => item.feature === featureName);
            const snippetLines = detail ? detail.snippet_lines || [] : [];
            return `
              <div class="list-card">
                <div class="list-card-header">
                  <div>
                    <div class="list-card-title">${{escapeHtml(fileNode.label)}}</div>
                    <div class="list-card-subtitle">
                      ${{fileNode.shared ? 'Shared with ' + (fileNode.feature_count - 1) + ' other features' : 'Feature-specific file'}}
                      · lines ${{escapeHtml(detail ? detail.line_number_preview : 'n/a')}}
                    </div>
                  </div>
                  <div class="pill">${{fileNode.per_feature_lines?.[featureName] || 0}} LoC</div>
                </div>
                ${{
                  snippetLines.length ? `
                    <details class="code-block">
                      <summary>Source LoC</summary>
                      <div class="code-meta">Expandable inline view for removable lines in ${{escapeHtml(fileNode.label)}}</div>
                      <div class="code-view">
                        ${{
                          snippetLines.map(line => `
                            <div class="code-line">
                              <span class="line-number">${{line.line_number ?? ''}}</span>
                              <span class="line-content">${{escapeHtml(line.content)}}</span>
                            </div>
                          `).join('')
                        }}
                      </div>
                    </details>` : ''
                }}
              </div>`;
          }}).join('') || '<div class="empty-state">No file details are available for this feature.</div>'
        }}
      </div>`;
  }}

  function renderFileDetails(fileNode) {{
    const details = (fileNode.per_feature_details || [])
      .slice()
      .sort((a, b) => b.line_count - a.line_count);

    detailsEyebrow.textContent = fileNode.shared ? 'Shared file' : 'File';
    detailsTitle.textContent = fileNode.label;
    detailsSubtitle.textContent = fileNode.shared
      ? `This file is touched by ${{fileNode.feature_count}} features.`
      : 'This file maps cleanly to a single feature.';
    detailsBody.innerHTML = `
      <div class="detail-grid">
        <div class="detail-card">
          <div class="detail-card-label">Total removable LoC</div>
          <div class="detail-card-value">${{fileNode.total_lines || 0}}</div>
        </div>
        <div class="detail-card">
          <div class="detail-card-label">Feature count</div>
          <div class="detail-card-value">${{fileNode.feature_count || 0}}</div>
        </div>
      </div>
      <div class="detail-section">
        <h3>Feature ownership</h3>
        <div class="feature-chip-row">
          ${{
            (fileNode.features || []).map(formatFeatureChip).join('') ||
            '<div class="empty-state">No feature associations recorded.</div>'
          }}
        </div>
      </div>
      <div class="detail-section">
        <h3>Expandable source LoC</h3>
        ${{
          details.map(detail => `
            <div class="list-card">
              <div class="list-card-header">
                <div>
                  <div class="list-card-title">${{escapeHtml(detail.feature)}}</div>
                  <div class="list-card-subtitle">Removable lines ${{escapeHtml(detail.line_number_preview || 'n/a')}}</div>
                </div>
                <div class="pill">${{detail.line_count}} LoC</div>
              </div>
              <details class="code-block">
                <summary>Source LoC</summary>
                <div class="code-meta">Inline source snippet for ${{escapeHtml(detail.feature)}}</div>
                <div class="code-view">
                  ${{
                    (detail.snippet_lines || []).map(line => `
                      <div class="code-line">
                        <span class="line-number">${{line.line_number ?? ''}}</span>
                        <span class="line-content">${{escapeHtml(line.content)}}</span>
                      </div>
                    `).join('')
                  }}
                </div>
              </details>
            </div>
          `).join('') || '<div class="empty-state">No source snippet details are available for this file.</div>'
        }}
      </div>`;
  }}

  function setActiveNode(nodeId) {{
    activeNodeId = nodeId;
    node.classed('selected', item => item.id === nodeId);
    const selected = nodeMap[nodeId];
    if (!selected) {{
      renderOverview();
      return;
    }}
    if (selected.type === 'feature') renderFeatureDetails(selected.label);
    else renderFileDetails(selected);
  }}

  function applyFeatureFocus(featureName) {{
    const featureId = `feat_${{featureName}}`;
    const connectedIds = new Set([featureId]);
    const connectedFileIds = new Set();
    GRAPH_DATA.edges.forEach(edge => {{
      const sourceId = typeof edge.source === 'object' ? edge.source.id : edge.source;
      const targetId = typeof edge.target === 'object' ? edge.target.id : edge.target;
      if (sourceId === featureId) {{
        connectedIds.add(targetId);
        connectedFileIds.add(targetId);
      }}
    }});
    GRAPH_DATA.edges.forEach(edge => {{
      const sourceId = typeof edge.source === 'object' ? edge.source.id : edge.source;
      const targetId = typeof edge.target === 'object' ? edge.target.id : edge.target;
      if (
        connectedFileIds.has(sourceId)
        && (edge.features || []).includes(featureName)
      ) {{
        connectedIds.add(targetId);
      }}
    }});

    node.classed('dimmed', item => !connectedIds.has(item.id));
    link.classed('dimmed', edge => {{
      const sourceId = typeof edge.source === 'object' ? edge.source.id : edge.source;
      const targetId = typeof edge.target === 'object' ? edge.target.id : edge.target;
      return !(
        (sourceId === featureId && connectedIds.has(targetId))
        || (
          connectedFileIds.has(sourceId)
          && connectedIds.has(targetId)
          && (edge.features || []).includes(featureName)
        )
      );
    }});
  }}

  function selectFeature(featureName) {{
    if (activeFeature === featureName) {{
      clearSelection();
      return;
    }}

    activeFeature = featureName;
    featureList.querySelectorAll('.feature-item').forEach(item => {{
      item.classList.toggle('active', item.dataset.feature === featureName);
    }});
    clearBtn.classList.add('visible');
    applyFeatureFocus(featureName);
    updateStats(featureName);
    setActiveNode(`feat_${{featureName}}`);
  }}

  function selectFile(fileNode) {{
    activeFeature = null;
    featureList.querySelectorAll('.feature-item').forEach(item => item.classList.remove('active'));
    clearBtn.classList.add('visible');

    const connectedFeatureIds = new Set((fileNode.features || []).map(feature => `feat_${{feature}}`));
    connectedFeatureIds.add(fileNode.id);
    GRAPH_DATA.edges.forEach(edge => {{
      const sourceId = typeof edge.source === 'object' ? edge.source.id : edge.source;
      const targetId = typeof edge.target === 'object' ? edge.target.id : edge.target;
      if (sourceId === fileNode.id) connectedFeatureIds.add(targetId);
    }});

    node.classed('dimmed', item => !connectedFeatureIds.has(item.id));
    link.classed('dimmed', edge => {{
      const sourceId = typeof edge.source === 'object' ? edge.source.id : edge.source;
      const targetId = typeof edge.target === 'object' ? edge.target.id : edge.target;
      return sourceId !== fileNode.id && targetId !== fileNode.id;
    }});

    updateStats(null);
    setActiveNode(fileNode.id);
  }}

  function clearSelection() {{
    activeFeature = null;
    activeNodeId = null;
    featureList.querySelectorAll('.feature-item').forEach(item => item.classList.remove('active'));
    clearBtn.classList.remove('visible');
    node.classed('dimmed', false).classed('selected', false);
    link.classed('dimmed', false);
    updateStats(null);
    renderOverview();
  }}

  GRAPH_DATA.features.forEach(feature => {{
    const featureNode = GRAPH_DATA.nodes.find(item => item.id === `feat_${{feature}}`);
    const li = document.createElement('li');
    li.className = 'feature-item';
    li.dataset.feature = feature;
    li.innerHTML = `
      <span class="dot" style="background:${{featureColors[feature]}}"></span>
      <span>
        <span class="name">${{escapeHtml(feature)}}</span>
        <span class="meta">${{featureNode ? featureNode.file_count + ' files' : '0 files'}}</span>
      </span>
      <span class="count">${{featureNode ? featureNode.removable_lines : 0}} lines</span>`;
    li.onclick = () => selectFeature(feature);
    featureList.appendChild(li);
  }});

  clearBtn.onclick = clearSelection;

  function updateStats(featureName) {{
    if (!featureName) {{
      const totalFiles = GRAPH_DATA.nodes.filter(item => item.type === 'file').length;
      const sharedFiles = GRAPH_DATA.nodes.filter(item => item.type === 'file' && item.shared).length;
      statsPanel.innerHTML = `
        <div class="stat-row"><span>Total features</span><span class="stat-val">${{GRAPH_DATA.features.length}}</span></div>
        <div class="stat-row"><span>Total files</span><span class="stat-val">${{totalFiles}}</span></div>
        <div class="stat-row"><span>Shared files</span><span class="stat-val">${{sharedFiles}}</span></div>
        <div class="stat-row"><span>Removable lines</span><span class="stat-val">${{GRAPH_DATA.total_removable_lines}}</span></div>`;
      return;
    }}

    const featureNode = GRAPH_DATA.nodes.find(item => item.id === `feat_${{featureName}}`);
    if (!featureNode) return;
    statsPanel.innerHTML = `
      <div class="stat-row"><span>Feature</span><span class="stat-val" style="color:${{featureColors[featureName]}}">${{escapeHtml(featureName)}}</span></div>
      <div class="stat-row"><span>Removable lines</span><span class="stat-val">${{featureNode.removable_lines}}</span></div>
      <div class="stat-row"><span>Files affected</span><span class="stat-val">${{featureNode.file_count}}</span></div>`;
  }}

  let searchTimeout;
  searchInput.addEventListener('input', () => {{
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {{
      const query = searchInput.value.toLowerCase();

      featureList.querySelectorAll('.feature-item').forEach(item => {{
        item.style.display = item.textContent.toLowerCase().includes(query) ? '' : 'none';
      }});

      if (query.length > 1) {{
        node.classed('dimmed', item => {{
          if (!query) return false;
          const featureMatch = (item.features || []).some(feature => feature.toLowerCase().includes(query));
          return !item.label.toLowerCase().includes(query) && !featureMatch;
        }});
        link.classed('dimmed', edge => {{
          const source = typeof edge.source === 'object' ? edge.source : nodeMap[edge.source];
          const target = typeof edge.target === 'object' ? edge.target : nodeMap[edge.target];
          const sourceMatch = source && source.label.toLowerCase().includes(query);
          const targetMatch = target && (
            target.label.toLowerCase().includes(query)
            || (target.features || []).some(feature => feature.toLowerCase().includes(query))
          );
          return !(sourceMatch || targetMatch);
        }});
      }} else if (activeFeature) {{
        applyFeatureFocus(activeFeature);
      }} else if (activeNodeId && nodeMap[activeNodeId] && nodeMap[activeNodeId].type === 'file') {{
        selectFile(nodeMap[activeNodeId]);
      }} else {{
        node.classed('dimmed', false);
        link.classed('dimmed', false);
      }}
    }}, 250);
  }});

  node.on('mouseover', (event, item) => {{
    let html = `<div class="tt-title">${{escapeHtml(item.label)}}</div>`;
    if (item.type === 'feature') {{
      html += `<div class="tt-row"><span>Removable lines</span><span class="tt-val">${{item.removable_lines}}</span></div>`;
      html += `<div class="tt-row"><span>Files affected</span><span class="tt-val">${{item.file_count}}</span></div>`;
      if (item.description) {{
        html += `<div style="margin-top:6px;color:var(--text-muted);font-size:11px">${{escapeHtml(item.description)}}</div>`;
      }}
    }} else {{
      html += `<div class="tt-row"><span>Total lines</span><span class="tt-val">${{item.total_lines}}</span></div>`;
      html += `<div class="tt-row"><span>Shared</span><span class="tt-val">${{item.shared ? 'Yes (' + item.feature_count + ' features)' : 'No'}}</span></div>`;
      const primaryDetail = (item.per_feature_details || [])[0];
      if (primaryDetail && primaryDetail.line_number_preview) {{
        html += `<div class="tt-row"><span>Line range</span><span class="tt-val">${{escapeHtml(primaryDetail.line_number_preview)}}</span></div>`;
      }}
      Object.entries(item.per_feature_lines || {{}}).forEach(([feature, count]) => {{
        html += `<div class="tt-row"><span style="color:${{featureColors[feature] || 'var(--primary)'}}">${{escapeHtml(feature)}}</span><span class="tt-val">${{count}}</span></div>`;
      }});
    }}

    tooltip.innerHTML = html;
    tooltip.classList.add('visible');
    const rect = container.getBoundingClientRect();
    tooltip.style.left = (event.clientX - rect.left + 12) + 'px';
    tooltip.style.top = (event.clientY - rect.top - 10) + 'px';
  }});

  node.on('mousemove', event => {{
    const rect = container.getBoundingClientRect();
    tooltip.style.left = (event.clientX - rect.left + 12) + 'px';
    tooltip.style.top = (event.clientY - rect.top - 10) + 'px';
  }});

  node.on('mouseout', () => {{
    tooltip.classList.remove('visible');
  }});

  node.on('click', (event, item) => {{
    if (item.type === 'feature') selectFeature(item.label);
    else selectFile(item);
  }});

  updateStats(null);
  renderOverview();
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

    The output is a single self-contained file: the vendored D3 build from
    :mod:`prat.web` is inlined, so the graph renders offline.
    """
    print(f"[+] Generating interactive feature graph: {output_path}")

    graph_json = json.dumps(graph.to_dict()).replace("</", "<\\/")

    html = _GRAPH_HTML_TEMPLATE.format(
        project=graph.project,
        feature_count=len(graph.features),
        total_lines=graph.total_removable_lines,
        graph_json=graph_json,
    )
    # D3 is substituted after ``.format`` so its braces never reach the formatter.
    d3_source = load_d3_bundle()
    if "</script" in d3_source.lower():
        raise RuntimeError("Vendored D3 contains a closing script tag; refusing to inline it")
    html = html.replace("__PRAT_D3_SOURCE__", d3_source, 1)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html)

    print(f"[+] Feature graph generated: {output_path}")
    return output_path
