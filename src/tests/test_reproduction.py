"""End-to-end guards for the public reproduction and validation entry points."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

from prat.cli import _REPRODUCE_DEMOS, run_reproduce
from prat.docker_runner import ContainerResult

ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str, relative_path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class TestDemoRunner:
    def test_help_starts_without_loading_metadata_as_a_target(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "src/demo-runner.py"), "--help"],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert "PRAT Demo Runner" in proc.stdout

    def test_observational_targets_have_no_numeric_range(self):
        runner = load_script("prat_demo_runner_test", "src/demo-runner.py")
        assert "_note" not in runner.EXPECTED_RESULTS
        assert runner.EXPECTED_RESULTS["aom-encoder"].is_scored is False

    def test_target_metadata_is_consistent_across_entry_points(self):
        runner = load_script("prat_demo_runner_consistency", "src/demo-runner.py")
        expected = json.loads(
            (ROOT / "paper_expected_results.json").read_text()
        )["targets"]
        expected_names = {
            name for name, value in expected.items()
            if not name.startswith("_") and isinstance(value, dict)
        }

        assert set(runner.DEMO_CONFIGS) == expected_names
        assert set(_REPRODUCE_DEMOS) == expected_names

        workflow = (ROOT / ".github/workflows/reproducibility.yml").read_text()
        makefile = (ROOT / "Makefile").read_text()
        normalize = lambda value: "".join(  # noqa: E731
            char for char in str(value).lower() if char.isalnum()
        )
        for name, config in runner.DEMO_CONFIGS.items():
            spec = expected[name]
            dockerfile = ROOT / config["dockerfile"]
            text = dockerfile.read_text()

            assert dockerfile.is_file()
            assert normalize(config["feature"]) == normalize(spec["feature"])
            assert spec["commit"] in text
            assert f'"--feature", "{config["feature"]}"' in text
            assert '"--remove"' in text
            assert f"- {name}" in workflow
            assert name in makefile

    def test_failed_rerun_cannot_leave_a_stale_checkpoint(self, tmp_path):
        runner = load_script("prat_demo_runner_stale_test", "src/demo-runner.py")
        output = tmp_path / "mosquitto-tls"
        output.mkdir()
        (output / "workflow_checkpoint.json").write_text('{"success": true}')

        failure = ContainerResult(
            success=False,
            exit_code=2,
            stdout="",
            stderr="failed",
            error_message="container failed",
        )
        with patch.object(runner, "run_docker_container", return_value=failure):
            result = runner.run_demo("mosquitto-tls", str(tmp_path))

        assert result.success is False
        assert not (output / "workflow_checkpoint.json").exists()
        assert (output / "demo_manifest.json").exists()


class TestReproduceCommand:
    def test_build_failure_is_propagated(self):
        with (
            patch("prat.cli.check_docker_available", return_value=True),
            patch("subprocess.run", return_value=MagicMock(returncode=7)),
        ):
            assert run_reproduce(["mosquitto-tls", "--no-validate"]) == 7

    def test_validation_failure_is_propagated(self):
        outcomes = [
            MagicMock(returncode=0),
            MagicMock(returncode=0),
            MagicMock(returncode=3),
        ]
        with (
            patch("prat.cli.check_docker_available", return_value=True),
            patch("subprocess.run", side_effect=outcomes),
        ):
            assert run_reproduce(["mosquitto-tls"]) == 3


class TestPaperValidator:
    def _bundle(
        self,
        tmp_path,
        *,
        lines=100,
        dynamic=True,
        run_id="run-1",
        expected_digest="fixture-expected",
    ):
        target = tmp_path / "demo"
        target.mkdir()
        checkpoint = {
            "success": True,
            "run_id": run_id,
            "project": "mosquitto",
            "feature": "TLS",
            "coverage_enabled": {
                "dynamic_execution": dynamic,
                "execution_succeeded": 1 if dynamic else 0,
                "execution_failed": 0,
                "execution_timed_out": 0,
            },
            "coverage_disabled": {
                "dynamic_execution": dynamic,
                "execution_succeeded": 1 if dynamic else 0,
                "execution_failed": 0,
                "execution_timed_out": 0,
            },
            "extraction_result": {
                "total_removable_lines": lines,
                "feature_only_removable_lines": 0,
                "file_line_counts": {"src/tls.c": lines},
                "feature_only_source_paths": [],
            },
            "removal_result": {
                "success": True,
                "lines_removed": lines,
            },
            "verification_result": {
                "success": True,
                "status": "passed",
                "compiles": True,
                "total_tests_run": 1,
                "total_tests_failed": 0,
                "crashes": [],
                "diverged_suites": [],
            },
        }
        (target / "workflow_checkpoint.json").write_text(json.dumps(checkpoint))
        manifest_path = target / "manifest.json"
        checkpoint_path = target / "workflow_checkpoint.json"
        manifest_path.write_text(json.dumps({
            "run_id": run_id,
            "project_name": "mosquitto",
            "feature": "TLS",
            "project_git_commit": "abc123",
            "build_system": "make",
            "success": True,
        }))
        artifact_hashes = {
            "workflow_checkpoint.json": hashlib.sha256(
                checkpoint_path.read_bytes()
            ).hexdigest(),
            "manifest.json": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        }
        (target / "demo_manifest.json").write_text(json.dumps({
            "run_id": run_id,
            "artifact_sha256": artifact_hashes,
            "provenance": {
                "prat_git_commit": "def456",
                "prat_source_sha256": "source-digest",
                "dockerfile_sha256": "dockerfile-digest",
                "expected_results_sha256": expected_digest,
                "image_id": "sha256:image",
            },
        }))
        return target

    @staticmethod
    def expected():
        return {
            "project": "mosquitto",
            "project_id": "mosquitto",
            "feature": "TLS",
            "commit": "abc123",
            "paper_feature": True,
            "paper_lines_removed": 100,
            "paper_lines_manual": 0,
            "min_acceptable": 90,
            "max_acceptable": 110,
            "tolerance_pct": 10,
            "key_files": ["tls.c"],
        }

    def test_valid_current_evidence_passes(self, tmp_path):
        validator = load_script(
            "prat_validator_valid_test", "scripts/validate_paper_results.py"
        )
        target = self._bundle(tmp_path)
        checkpoint = json.loads((target / "workflow_checkpoint.json").read_text())
        manifest = json.loads((target / "manifest.json").read_text())
        host = json.loads((target / "demo_manifest.json").read_text())

        result = validator.validate_target(
            "demo", self.expected(), checkpoint, manifest, host, strict=True
        )

        assert result.status == "COMPATIBLE"
        assert result.provenance["source_commit"] == "abc123"
        assert result.provenance["checkpoint_run_id"] == "run-1"
        assert result.provenance["host"]["image_id"] == "sha256:image"

    def test_zero_cannot_reproduce_nonzero_paper_result(self, tmp_path):
        validator = load_script(
            "prat_validator_zero_test", "scripts/validate_paper_results.py"
        )
        target = self._bundle(tmp_path, lines=0)
        checkpoint = json.loads((target / "workflow_checkpoint.json").read_text())
        manifest = json.loads((target / "manifest.json").read_text())
        host = json.loads((target / "demo_manifest.json").read_text())

        result = validator.validate_target(
            "demo", self.expected(), checkpoint, manifest, host, strict=True
        )

        assert result.status == "FAIL"
        assert "zero mapped lines" in result.error_message

    def test_compile_time_coverage_is_rejected(self, tmp_path):
        validator = load_script(
            "prat_validator_dynamic_test", "scripts/validate_paper_results.py"
        )
        target = self._bundle(tmp_path, dynamic=False)
        checkpoint = json.loads((target / "workflow_checkpoint.json").read_text())
        manifest = json.loads((target / "manifest.json").read_text())
        host = json.loads((target / "demo_manifest.json").read_text())

        result = validator.validate_target(
            "demo", self.expected(), checkpoint, manifest, host, strict=True
        )

        assert result.status == "FAIL"
        assert "not dynamically executed" in result.error_message

    def test_mismatched_run_ids_are_rejected(self, tmp_path):
        validator = load_script(
            "prat_validator_run_id_test", "scripts/validate_paper_results.py"
        )
        target = self._bundle(tmp_path)
        checkpoint = json.loads((target / "workflow_checkpoint.json").read_text())
        manifest = json.loads((target / "manifest.json").read_text())

        result = validator.validate_target(
            "demo",
            self.expected(),
            checkpoint,
            manifest,
            {"run_id": "different"},
            strict=True,
        )

        assert result.status == "FAIL"
        assert "run IDs" in result.error_message

    def test_mismatched_source_commit_is_rejected(self, tmp_path):
        validator = load_script(
            "prat_validator_commit_test", "scripts/validate_paper_results.py"
        )
        target = self._bundle(tmp_path)
        checkpoint = json.loads((target / "workflow_checkpoint.json").read_text())
        manifest = json.loads((target / "manifest.json").read_text())
        manifest["project_git_commit"] = "wrong"
        host = json.loads((target / "demo_manifest.json").read_text())

        result = validator.validate_target(
            "demo", self.expected(), checkpoint, manifest, host, strict=True
        )

        assert result.status == "FAIL"
        assert "pinned commit" in result.error_message

    def test_strict_validation_requires_removal_and_verification(self, tmp_path):
        validator = load_script(
            "prat_validator_removal_test", "scripts/validate_paper_results.py"
        )
        target = self._bundle(tmp_path)
        checkpoint = json.loads((target / "workflow_checkpoint.json").read_text())
        checkpoint["removal_result"] = None
        checkpoint["verification_result"] = None
        manifest = json.loads((target / "manifest.json").read_text())
        host = json.loads((target / "demo_manifest.json").read_text())

        result = validator.validate_target(
            "demo", self.expected(), checkpoint, manifest, host, strict=True
        )

        assert result.status == "FAIL"
        assert "successful source removal" in result.error_message

    def test_validation_can_be_scoped_to_one_target(self, tmp_path):
        validator = load_script(
            "prat_validator_scope_test", "scripts/validate_paper_results.py"
        )
        expected_path = tmp_path / "expected.json"
        expected = self.expected()
        expected_path.write_text(json.dumps({
            "targets": {
                "_note": "metadata",
                "demo": expected,
                "missing-demo": expected,
            }
        }))
        self._bundle(
            tmp_path,
            expected_digest=hashlib.sha256(expected_path.read_bytes()).hexdigest(),
        )

        report = validator.run_validation(
            tmp_path,
            expected_path,
            strict=True,
            target_names=["demo"],
        )

        assert report.total_targets == 1
        assert report.success is True


class TestBatchValidator:
    def test_complete_algorithm_checkpoint_passes(self):
        validator = load_script(
            "prat_batch_validator_test", "scripts/validate_batch_results.py"
        )
        checkpoint = {
            "success": True,
            "project": "mosquitto",
            "run_id": "run-1",
            "source_commit": "abc123",
            "features_discovered": 19,
            "features_analyzed": 18,
            "features_failed": 1,
            "builds_performed": 21,
            "baseline_all_features": True,
            "symbolic_test_count": 10,
            "union_removable_lines": 42,
            "mapping_build_states": [
                {f"f{i}": True for i in range(19)},
                *[
                    {f"f{i}": i != excluded for i in range(19)}
                    for excluded in range(19)
                ],
            ],
            "baseline_coverage": {
                "success": True,
                "dynamic_execution": True,
                "execution_succeeded": 1,
                "execution_failed": 0,
                "execution_timed_out": 0,
                "test_plan_id": "plan-1",
            },
            "features": {
                **{
                    f"f{i}": {
                        "analyzed": True,
                        "coverage": {
                            "success": True,
                            "dynamic_execution": True,
                            "execution_succeeded": 1,
                            "execution_failed": 0,
                            "execution_timed_out": 0,
                            "test_plan_id": "plan-1",
                        },
                    }
                    for i in range(18)
                },
                "f18": {
                    "analyzed": False,
                    "failure_stage": "compilation",
                    "discarded_reason": "does not compile",
                },
            },
            "feature_names": [f"f{i}" for i in range(19)],
            "removal_result": {"success": True, "lines_removed": 42},
            "verification_result": {
                "success": True,
                "compiles": True,
                "total_tests_run": 1,
                "total_tests_failed": 0,
                "crashes": [],
                "diverged_suites": [],
                "klee_replay_results": {
                    f"test{i}.ktest": True for i in range(10)
                },
            },
        }
        expected = {
            "feature_counts": {
                "Mosquitto": {"features": 19},
            }
        }

        assert validator.validate_batch(checkpoint, expected, strict=True) == []

    def test_incomplete_feature_discovery_fails(self):
        validator = load_script(
            "prat_batch_validator_count_test", "scripts/validate_batch_results.py"
        )
        checkpoint = {
            "success": True,
            "project": "mosquitto",
            "run_id": "run-1",
            "source_commit": "abc123",
            "features_discovered": 18,
            "features_analyzed": 18,
            "features_failed": 0,
            "builds_performed": 19,
            "baseline_all_features": True,
            "mapping_build_states": [],
            "baseline_coverage": {
                "success": True,
                "dynamic_execution": True,
                "execution_succeeded": 1,
                "execution_failed": 0,
                "execution_timed_out": 0,
                "test_plan_id": "plan-1",
            },
            "features": {
                f"f{i}": {
                    "analyzed": True,
                    "coverage": {
                        "success": True,
                        "dynamic_execution": True,
                        "execution_succeeded": 1,
                        "execution_failed": 0,
                        "execution_timed_out": 0,
                        "test_plan_id": "plan-1",
                    },
                }
                for i in range(18)
            },
            "feature_names": [f"f{i}" for i in range(18)],
        }
        expected = {
            "feature_counts": {
                "Mosquitto": {"features": 19},
            }
        }

        errors = validator.validate_batch(checkpoint, expected, strict=False)
        assert any("paper reports 19" in error for error in errors)
