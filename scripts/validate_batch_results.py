#!/usr/bin/env python3
"""Validate one Algorithm 1 batch checkpoint against paper-level invariants."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ALIASES = {
    "aom": "libaom",
    "ffmpeg": "FFmpeg",
    "mosquitto": "Mosquitto",
    "opendds": "OpenDDS",
    "quiche": "Quiche",
    "rav1e": "rav1e",
    "azureuamqpc": "azure-uamqp-c",
}


def normalize(value: object) -> str:
    return "".join(char for char in str(value or "").lower() if char.isalnum())


def resolve_project(checkpoint_project: object, feature_counts: dict) -> str | None:
    normalized = normalize(checkpoint_project)
    alias = PROJECT_ALIASES.get(normalized)
    if alias in feature_counts:
        return alias
    for name in feature_counts:
        if not name.startswith("_") and normalize(name) == normalized:
            return name
    return None


def validate_batch(checkpoint: dict, expected: dict, strict: bool) -> list[str]:
    """Return invariant violations; an empty list means the checkpoint passes."""
    errors: list[str] = []
    feature_counts = expected["feature_counts"]
    project = resolve_project(checkpoint.get("project"), feature_counts)
    if project is None:
        return [f"unknown project identity: {checkpoint.get('project')!r}"]

    paper_count = int(feature_counts[project]["features"])
    discovered = int(checkpoint.get("features_discovered", -1))
    analyzed = int(checkpoint.get("features_analyzed", -1))
    failed = int(checkpoint.get("features_failed", -1))
    features = checkpoint.get("features")
    if not checkpoint.get("run_id"):
        errors.append("batch checkpoint has no run identity")
    if not checkpoint.get("source_commit"):
        errors.append("batch checkpoint has no source commit")

    if checkpoint.get("success") is not True:
        errors.append("batch checkpoint does not record success")
    if discovered != paper_count:
        errors.append(
            f"discovered {discovered} features; paper reports {paper_count}"
        )
    if analyzed + failed != discovered:
        errors.append(
            "analyzed plus discarded feature counts do not cover discovery"
        )
    if checkpoint.get("baseline_all_features") is not True:
        errors.append("baseline was not built with every discovered feature enabled")
    build_states = checkpoint.get("mapping_build_states")
    if not isinstance(build_states, list) or len(build_states) != discovered + 1:
        errors.append("mapping build records do not prove Algorithm 1's n+1 builds")
    else:
        feature_names = set(features) if isinstance(features, dict) else set()
        all_enabled = {name: True for name in feature_names}
        expected_states = [all_enabled] + [
            {name: name != excluded for name in feature_names}
            for excluded in sorted(feature_names)
        ]
        normalized_states = [
            {str(name): bool(state) for name, state in item.items()}
            for item in build_states
            if isinstance(item, dict)
        ]
        if len(normalized_states) != len(build_states):
            errors.append("mapping build state evidence is malformed")
        elif sorted(
            (sorted(item.items()) for item in normalized_states),
            key=str,
        ) != sorted(
            (sorted(item.items()) for item in expected_states),
            key=str,
        ):
            errors.append(
                "mapping builds are not one all-enabled plus one leave-one-out "
                "state per feature"
            )

    if not isinstance(features, dict) or len(features) != discovered:
        errors.append("per-feature evidence is incomplete")
    else:
        if sorted(checkpoint.get("feature_names", [])) != sorted(features):
            errors.append("feature identity list does not match feature evidence")
        analyzed_evidence = 0
        discarded_evidence = 0
        for name, evidence in features.items():
            if not isinstance(evidence, dict):
                errors.append(f"{name}: feature evidence is not an object")
                continue
            if evidence.get("analyzed") is True:
                analyzed_evidence += 1
                coverage = evidence.get("coverage")
                if not _valid_dynamic_coverage(coverage):
                    errors.append(
                        f"{name}: analyzed feature lacks successful dynamic coverage"
                    )
            else:
                discarded_evidence += 1
                if evidence.get("failure_stage") != "compilation":
                    errors.append(
                        f"{name}: only a failed leave-one-out build may be discarded"
                    )
                if not evidence.get("discarded_reason"):
                    errors.append(f"{name}: discarded option has no reason")
        if analyzed_evidence != analyzed:
            errors.append("analyzed feature count does not match feature evidence")
        if discarded_evidence != failed:
            errors.append("discarded feature count does not match feature evidence")

    baseline = checkpoint.get("baseline_coverage")
    if not _valid_dynamic_coverage(baseline):
        errors.append("all-feature baseline lacks successful dynamic coverage")
    expected_plan = (
        baseline.get("test_plan_id") if isinstance(baseline, dict) else None
    )
    if not expected_plan:
        errors.append("all-feature baseline has no test-plan digest")
    elif isinstance(features, dict):
        for name, evidence in features.items():
            if (
                isinstance(evidence, dict)
                and evidence.get("analyzed") is True
                and isinstance(evidence.get("coverage"), dict)
                and evidence["coverage"].get("test_plan_id") != expected_plan
            ):
                errors.append(f"{name}: coverage used a different test plan")

    if strict:
        if int(checkpoint.get("symbolic_test_count", 0)) < 1:
            errors.append("strict paper algorithm requires generated symbolic tests")
        removal = checkpoint.get("removal_result")
        if not isinstance(removal, dict) or removal.get("success") is not True:
            errors.append("strict paper algorithm requires successful union removal")
        else:
            union_lines = checkpoint.get("union_removable_lines")
            if (
                not isinstance(union_lines, int)
                or removal.get("lines_removed") != union_lines
                or removal.get("target_lines") not in (None, union_lines)
                or removal.get("missing_source_files")
                or removal.get("skipped_unbalanced")
            ):
                errors.append(
                    "union removal accounting does not match the complete mapped set"
                )
            elif int(removal.get("absorbed_structural", 0)) < 0:
                errors.append(
                    "union removal structural-line accounting is invalid"
                )
        verification = checkpoint.get("verification_result")
        if (
            not isinstance(verification, dict)
            or verification.get("success") is not True
        ):
            errors.append(
                "strict paper algorithm requires successful union verification"
            )
        elif (
            verification.get("compiles") is not True
            or int(verification.get("total_tests_run", 0)) < 1
            or int(verification.get("total_tests_failed", 0)) != 0
            or verification.get("crashes")
            or verification.get("diverged_suites")
        ):
            errors.append("union verification evidence is incomplete")
        elif int(checkpoint.get("symbolic_test_count", 0)) > 0:
            replay = verification.get("klee_replay_results")
            if (
                not isinstance(replay, dict)
                or len(replay) != int(checkpoint["symbolic_test_count"])
                or not all(replay.values())
            ):
                errors.append(
                    "union verification did not pass every generated symbolic test"
                )

    return errors


def _valid_dynamic_coverage(value: object) -> bool:
    """Check the execution gate recorded by ``CoverageResult``."""
    if not isinstance(value, dict):
        return False
    return (
        value.get("success") is True
        and value.get("dynamic_execution") is True
        and (
            int(value.get("execution_succeeded", 0))
            + int(value.get("symbolic_tests_replayed", 0))
            >= 1
        )
        and int(value.get("execution_failed", 0)) == 0
        and int(value.get("execution_timed_out", 0)) == 0
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a PRAT batch checkpoint against Algorithm 1"
    )
    parser.add_argument("checkpoint", help="Path to batch_checkpoint.json")
    parser.add_argument(
        "--expected",
        default=str(Path(__file__).parent.parent / "paper_expected_results.json"),
    )
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    try:
        checkpoint = json.loads(Path(args.checkpoint).read_text())
        expected = json.loads(Path(args.expected).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[!] Cannot load validation input: {exc}", file=sys.stderr)
        return 2

    errors = validate_batch(checkpoint, expected, args.strict)
    if errors:
        print("FAIL")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("PASS: feature count, n+1 builds, all-feature baseline, and evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
