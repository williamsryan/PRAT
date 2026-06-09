#!/usr/bin/env python3
"""
Docker-friendly PRAT workflow entry point.

This script is intentionally small: Docker demos call it with a project,
feature, and output directory, and it runs the same package workflow that the
`prat` CLI uses. It also writes a compact manifest for review/debugging.
"""

import argparse
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Docker images copy this file into /prat/src without installing the package.
sys.path.insert(0, str(Path(__file__).parent))

from prat.adapters import get_adapter
from prat.workflow import WorkflowResult, run_complete_workflow


def _command_output(cmd: list[str], cwd: Optional[str] = None) -> Optional[str]:
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _artifact_paths(output_dir: Path, feature: str) -> dict[str, str]:
    feature_upper = feature.upper()
    candidates = {
        "checkpoint": output_dir / "workflow_checkpoint.json",
        "html_report": output_dir / "report.html",
        "json_report": output_dir / "report.json",
        "dot_graph": output_dir / "FDG.dot",
        "diff_dir": output_dir / f"diff_{feature}",
        "coverage_enabled": output_dir / f"coverage_files_WITH_{feature_upper}_yes",
        "coverage_disabled": output_dir / f"coverage_files_WITH_{feature_upper}_no",
    }
    return {
        name: str(path)
        for name, path in candidates.items()
        if path.exists()
    }


def _write_manifest(
    output_dir: Path,
    project_path: Path,
    feature: str,
    result: WorkflowResult,
) -> Path:
    adapter = get_adapter(str(project_path))
    extraction = result.extraction_result

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tool": "PRAT",
        "project_path": str(project_path),
        "project_name": project_path.name,
        "project_git_commit": _command_output(["git", "rev-parse", "HEAD"], cwd=str(project_path)),
        "feature": feature,
        "success": result.success,
        "checkpoint": result.checkpoint.value,
        "error_message": result.error_message,
        "total_time_seconds": result.total_time,
        "adapter": type(adapter).__name__ if adapter else None,
        "build_system": adapter.build_system.value if adapter else None,
        "coverage_tool": adapter.coverage_tool if adapter else None,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "environment": {
            "gcc": _command_output(["gcc", "--version"]),
            "gcov": _command_output(["gcov", "--version"]),
            "llvm-cov-9": _command_output(["llvm-cov-9", "--version"]),
        },
        "results": {
            "total_removable_lines": (
                extraction.total_removable_lines if extraction else None
            ),
            "files_analyzed": (
                len(extraction.file_line_counts) if extraction else None
            ),
        },
        "artifacts": _artifact_paths(output_dir, feature),
    }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[+] Manifest written to {manifest_path}")
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a PRAT demo workflow")
    parser.add_argument("--project", required=True, help="Path to target project")
    parser.add_argument("--feature", required=True, help="Feature to analyze")
    parser.add_argument("--output", required=True, help="Directory for workflow artifacts")
    parser.add_argument("--tests", action="store_true", help="Run project tests during builds")
    parser.add_argument(
        "--symbolic",
        action="store_true",
        help="Generate experimental KLEE symbolic tests",
    )
    args = parser.parse_args()

    project_path = Path(args.project).resolve()
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not project_path.exists():
        print(f"[!] Project path does not exist: {project_path}", file=sys.stderr)
        return 1

    print("=" * 70)
    print("PRAT Demo Workflow")
    print("=" * 70)
    print(f"Project: {project_path}")
    print(f"Feature: {args.feature}")
    print(f"Output:  {output_dir}")
    print("=" * 70)

    adapter = get_adapter(str(project_path))
    result = run_complete_workflow(
        project_path=str(project_path),
        feature=args.feature,
        run_tests=args.tests,
        output_dir=str(output_dir),
        adapter=adapter,
        symbolic=args.symbolic,
    )

    _write_manifest(output_dir, project_path, args.feature, result)
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
