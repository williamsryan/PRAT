"""Tests for prat.batch — Algorithm 1 across every discovered feature."""

from unittest.mock import MagicMock, patch

from prat.batch import (
    BatchResult,
    FeatureAnalysis,
    _build_cross_feature_map,
    _leave_one_out,
    run_batch_analysis,
)
from prat.compilation import BuildSystem, CompilationResult
from prat.coverage import CoverageResult
from prat.discovery import Feature
from prat.extraction import extract_from_mapping
from prat.mapping import map_feature
from prat.removal import RemovalResult
from prat.verification import VerificationResult, VerificationStatus

from .test_mapping import write_gcov


def make_feature(name, description=None):
    return Feature(name=name, description=description, raw_name=name)


def make_analysis(name, files, lines=None, discarded=None):
    """An analyzed (or discarded) FeatureAnalysis with the given affected files."""
    analysis = FeatureAnalysis(feature=make_feature(name))
    if discarded:
        analysis.discarded_reason = discarded
        return analysis
    analysis.affected_files = list(files)
    analysis.removable_lines = lines if lines is not None else len(files)
    # analyzed requires a mapping; a minimal real one keeps the invariant honest.
    analysis.mapping = _trivial_mapping(name)
    return analysis


def _trivial_mapping(name):
    from prat.mapping import FeatureMapping

    return FeatureMapping(feature=name)


class TestLeaveOneOut:
    def test_enables_every_feature_except_the_excluded_one(self):
        states = _leave_one_out(["TLS", "BRIDGE", "WS"], "BRIDGE")

        assert states == {"TLS": True, "BRIDGE": False, "WS": True}


class TestBuildCrossFeatureMap:
    def test_no_overlap(self):
        results = {
            "TLS": make_analysis("TLS", ["tls.c", "ssl.c"]),
            "BRIDGE": make_analysis("BRIDGE", ["bridge.c"]),
        }

        cmap = _build_cross_feature_map(results)

        assert cmap.shared_files == {}
        assert cmap.feature_to_files["TLS"] == {"tls.c", "ssl.c"}

    def test_shared_files_detected(self):
        results = {
            "TLS": make_analysis("TLS", ["net.c", "tls.c"]),
            "BRIDGE": make_analysis("BRIDGE", ["net.c", "bridge.c"]),
        }

        cmap = _build_cross_feature_map(results)

        assert cmap.shared_files == {"BRIDGE & TLS": ["net.c"]}

    def test_file_to_features_mapping(self):
        results = {
            "TLS": make_analysis("TLS", ["net.c"]),
            "BRIDGE": make_analysis("BRIDGE", ["net.c"]),
        }

        cmap = _build_cross_feature_map(results)

        assert cmap.file_to_features["net.c"] == {"TLS", "BRIDGE"}

    def test_discarded_features_are_excluded(self):
        results = {
            "TLS": make_analysis("TLS", ["net.c"]),
            "BROKEN": make_analysis("BROKEN", [], discarded="compilation failed"),
        }

        cmap = _build_cross_feature_map(results)

        assert "BROKEN" not in cmap.feature_to_files


class TestBatchResult:
    def test_union_counts_a_shared_line_once(self, tmp_path):
        """Table 4's PRAT column is |union of D_f|, not the sum of |D_f|."""
        enabled = tmp_path / "on"
        write_gcov(enabled, "src/net.c", {10: "1", 11: "1"})
        disabled_a = tmp_path / "off_a"
        write_gcov(disabled_a, "src/net.c", {11: "1"})
        disabled_b = tmp_path / "off_b"
        write_gcov(disabled_b, "src/net.c", {})

        mapping_a = map_feature("A", str(enabled), str(disabled_a))  # {10}
        mapping_b = map_feature("B", str(enabled), str(disabled_b))  # {10, 11}

        result = BatchResult(
            success=True, project="p", features_discovered=2,
            features_analyzed=2, features_failed=0,
            total_removable_lines=mapping_a.total_lines + mapping_b.total_lines,
        )
        for name, mapping in (("A", mapping_a), ("B", mapping_b)):
            analysis = FeatureAnalysis(feature=make_feature(name))
            analysis.mapping = mapping
            analysis.extraction = extract_from_mapping(mapping)
            result.feature_results[name] = analysis

        # Sum double-counts line 10; the union does not.
        assert result.total_removable_lines == 3
        assert result.union_removable_lines == 2


class TestRunBatchAnalysis:
    def test_symbolic_rust_batch_fails_closed(self, tmp_path):
        adapter = MagicMock(
            build_system=BuildSystem.CARGO,
            coverage_tool="cargo-llvm-cov",
            source_directories=["src"],
        )
        with patch(
            "prat.batch.discover_features",
            return_value=[make_feature("qlog")],
        ):
            result = run_batch_analysis(
                str(tmp_path),
                output_dir=str(tmp_path),
                adapter=adapter,
                symbolic=True,
            )

        assert result.success is False
        assert "full paper algorithm" in (result.error_message or "")
        assert (tmp_path / "batch_checkpoint.json").exists()

    def test_no_features_discovered_fails_cleanly(self, tmp_path):
        with patch("prat.batch.discover_features", return_value=[]):
            result = run_batch_analysis(str(tmp_path), adapter=MagicMock())

        assert result.success is False
        assert result.error_message == "No features discovered"
        assert (tmp_path / "batch_checkpoint.json").exists()

    def test_all_features_skipped_fails_cleanly(self, tmp_path):
        with patch("prat.batch.discover_features",
                   return_value=[make_feature("TLS")]):
            result = run_batch_analysis(
                str(tmp_path),
                skip_features=["TLS"],
                adapter=MagicMock(),
            )

        assert result.success is False
        assert "skipped" in result.error_message
        assert (tmp_path / "batch_checkpoint.json").exists()


class TestAlgorithmOneBuildCount:
    """The paper builds n+1 binaries: one baseline plus one per feature."""

    def _patched_batch(self, tmp_path, features, compile_mock, coverage_mock):
        adapter = MagicMock()
        adapter.get_execution_commands.return_value = [["make", "test"]]
        adapter.coverage_command_executes_tests.return_value = False
        return patch.multiple(
            "prat.batch",
            discover_features=lambda *a, **k: features,
            get_adapter=lambda *a, **k: adapter,
            compile_with_adapter=compile_mock,
            generate_coverage_with_adapter=coverage_mock,
            build_feature_graph=lambda *a, **k: None,
            generate_feature_graph_html=lambda *a, **k: None,
        )

    def test_performs_n_plus_one_builds(self, tmp_path):
        features = [make_feature("TLS"), make_feature("BRIDGE")]

        baseline = tmp_path / "cov_all"
        write_gcov(baseline, "src/net.c", {10: "1", 11: "1", 14: "9"})
        off_tls = tmp_path / "cov_tls_off"
        write_gcov(off_tls, "src/net.c", {11: "1", 14: "9"})
        off_bridge = tmp_path / "cov_bridge_off"
        write_gcov(off_bridge, "src/net.c", {10: "1", 14: "9"})

        builds = []

        def fake_compile(adapter, feature, enabled, run_tests, feature_states=None):
            builds.append(dict(feature_states or {}))
            return CompilationResult(
                success=True, binary_path=None, error_message=None,
                compilation_time=0.0, coverage_enabled=True,
                build_system=BuildSystem.MAKE,
            )

        def fake_coverage(adapter, feature, enabled, **kwargs):
            label = kwargs.get("label")
            if label == "all_features":
                directory = baseline
            else:
                directory = off_tls if feature == "TLS" else off_bridge
            return CoverageResult(
                success=True,
                coverage_files=[str(p) for p in directory.iterdir()],
                coverage_dir=str(directory),
                missing_files=[],
                dynamic_execution=True,
            )

        with self._patched_batch(tmp_path, features, fake_compile, fake_coverage):
            result = run_batch_analysis(str(tmp_path), output_dir=str(tmp_path))

        assert result.success is True
        assert result.builds_performed == len(features) + 1
        assert result.baseline_all_features is True
        # Baseline enables everything; each feature build leaves exactly one off.
        assert builds[0] == {"TLS": True, "BRIDGE": True}
        assert {"TLS": False, "BRIDGE": True} in builds
        assert {"TLS": True, "BRIDGE": False} in builds

    def test_maps_each_feature_against_the_shared_baseline(self, tmp_path):
        features = [make_feature("TLS"), make_feature("BRIDGE")]

        baseline = tmp_path / "cov_all"
        write_gcov(baseline, "src/net.c", {10: "1", 11: "1", 14: "9"})
        off_tls = tmp_path / "cov_tls_off"
        write_gcov(off_tls, "src/net.c", {11: "1", 14: "9"})
        off_bridge = tmp_path / "cov_bridge_off"
        write_gcov(off_bridge, "src/net.c", {10: "1", 14: "9"})

        def fake_compile(adapter, feature, enabled, run_tests, feature_states=None):
            return CompilationResult(
                success=True, binary_path=None, error_message=None,
                compilation_time=0.0, coverage_enabled=True,
                build_system=BuildSystem.MAKE,
            )

        def fake_coverage(adapter, feature, enabled, **kwargs):
            if kwargs.get("label") == "all_features":
                directory = baseline
            else:
                directory = off_tls if feature == "TLS" else off_bridge
            return CoverageResult(
                success=True,
                coverage_files=[str(p) for p in directory.iterdir()],
                coverage_dir=str(directory),
                missing_files=[],
                dynamic_execution=True,
            )

        with self._patched_batch(tmp_path, features, fake_compile, fake_coverage):
            result = run_batch_analysis(str(tmp_path), output_dir=str(tmp_path))

        assert result.feature_results["TLS"].extraction.file_line_numbers == {
            "src/net.c": [10]
        }
        assert result.feature_results["BRIDGE"].extraction.file_line_numbers == {
            "src/net.c": [11]
        }

    def test_discards_options_whose_build_fails(self, tmp_path):
        features = [make_feature("TLS"), make_feature("BROKEN")]

        baseline = tmp_path / "cov_all"
        write_gcov(baseline, "src/net.c", {10: "1", 14: "9"})
        off_tls = tmp_path / "cov_tls_off"
        write_gcov(off_tls, "src/net.c", {14: "9"})

        def fake_compile(adapter, feature, enabled, run_tests, feature_states=None):
            if feature == "BROKEN" and feature_states and not feature_states["BROKEN"]:
                return CompilationResult(
                    success=False, binary_path=None,
                    error_message="undefined reference to broken_symbol",
                    compilation_time=0.0, coverage_enabled=True,
                    build_system=BuildSystem.MAKE,
                )
            return CompilationResult(
                success=True, binary_path=None, error_message=None,
                compilation_time=0.0, coverage_enabled=True,
                build_system=BuildSystem.MAKE,
            )

        def fake_coverage(adapter, feature, enabled, **kwargs):
            directory = baseline if kwargs.get("label") == "all_features" else off_tls
            return CoverageResult(
                success=True,
                coverage_files=[str(p) for p in directory.iterdir()],
                coverage_dir=str(directory),
                missing_files=[],
                dynamic_execution=True,
            )

        with self._patched_batch(tmp_path, features, fake_compile, fake_coverage):
            result = run_batch_analysis(str(tmp_path), output_dir=str(tmp_path))

        assert result.features_analyzed == 1
        assert result.features_failed == 1
        assert "BROKEN" in result.discarded_options
        assert result.feature_results["BROKEN"].analyzed is False

    def test_all_features_build_failure_aborts_without_semantic_fallback(self, tmp_path):
        features = [make_feature("TLS")]

        baseline = tmp_path / "cov_defaults"
        write_gcov(baseline, "src/net.c", {10: "1", 14: "9"})
        off_tls = tmp_path / "cov_tls_off"
        write_gcov(off_tls, "src/net.c", {14: "9"})

        def fake_compile(adapter, feature, enabled, run_tests, feature_states=None):
            if feature_states is not None and all(feature_states.values()):
                return CompilationResult(
                    success=False, binary_path=None,
                    error_message="mutually exclusive options",
                    compilation_time=0.0, coverage_enabled=True,
                    build_system=BuildSystem.MAKE,
                )
            return CompilationResult(
                success=True, binary_path=None, error_message=None,
                compilation_time=0.0, coverage_enabled=True,
                build_system=BuildSystem.MAKE,
            )

        def fake_coverage(adapter, feature, enabled, **kwargs):
            directory = baseline if enabled else off_tls
            return CoverageResult(
                success=True,
                coverage_files=[str(p) for p in directory.iterdir()],
                coverage_dir=str(directory),
                missing_files=[],
                dynamic_execution=True,
            )

        with self._patched_batch(tmp_path, features, fake_compile, fake_coverage):
            result = run_batch_analysis(str(tmp_path), output_dir=str(tmp_path))

        assert result.success is False
        assert result.baseline_all_features is False
        assert "all-features" in (result.baseline_note or "")

    def test_coverage_failure_aborts_instead_of_discarding_the_feature(self, tmp_path):
        features = [make_feature("TLS")]
        baseline = tmp_path / "cov_all"
        write_gcov(baseline, "src/net.c", {10: "1"})

        def fake_compile(*_args, **_kwargs):
            return CompilationResult(
                success=True, binary_path=None, error_message=None,
                compilation_time=0.0, coverage_enabled=True,
                build_system=BuildSystem.MAKE,
            )

        def fake_coverage(_adapter, _feature, enabled, **_kwargs):
            if enabled:
                return CoverageResult(
                    success=True,
                    coverage_files=[str(p) for p in baseline.iterdir()],
                    coverage_dir=str(baseline),
                    missing_files=[],
                    dynamic_execution=True,
                )
            return CoverageResult(
                success=False,
                coverage_files=[],
                coverage_dir="",
                missing_files=[],
                error_message="test suite failed",
                dynamic_execution=False,
            )

        with self._patched_batch(tmp_path, features, fake_compile, fake_coverage):
            result = run_batch_analysis(str(tmp_path), output_dir=str(tmp_path))

        assert result.success is False
        assert "batch is incomplete" in (result.error_message or "")
        assert result.discarded_options == {}
        assert result.feature_results["TLS"].failure_stage == "coverage"
        assert (tmp_path / "batch_checkpoint.json").exists()

    def test_skip_features_are_not_analyzed(self, tmp_path):
        features = [make_feature("TLS"), make_feature("BRIDGE")]

        baseline = tmp_path / "cov_all"
        write_gcov(baseline, "src/net.c", {10: "1", 14: "9"})
        off_tls = tmp_path / "cov_tls_off"
        write_gcov(off_tls, "src/net.c", {14: "9"})

        analyzed = []

        def fake_compile(adapter, feature, enabled, run_tests, feature_states=None):
            return CompilationResult(
                success=True, binary_path=None, error_message=None,
                compilation_time=0.0, coverage_enabled=True,
                build_system=BuildSystem.MAKE,
            )

        def fake_coverage(adapter, feature, enabled, **kwargs):
            if kwargs.get("label") != "all_features":
                analyzed.append(feature)
            directory = baseline if kwargs.get("label") == "all_features" else off_tls
            return CoverageResult(
                success=True,
                coverage_files=[str(p) for p in directory.iterdir()],
                coverage_dir=str(directory),
                missing_files=[],
                dynamic_execution=True,
            )

        with self._patched_batch(tmp_path, features, fake_compile, fake_coverage):
            result = run_batch_analysis(
                str(tmp_path), output_dir=str(tmp_path), skip_features=["BRIDGE"]
            )

        assert analyzed == ["TLS"]
        assert result.features_discovered == 2
        assert "BRIDGE" not in result.feature_results

    def test_union_removal_and_verification_are_evidence_producers(self, tmp_path):
        features = [make_feature("TLS")]
        baseline = tmp_path / "cov_all"
        disabled = tmp_path / "cov_tls_off"
        write_gcov(baseline, "src/net.c", {10: "2", 14: "1"})
        write_gcov(disabled, "src/net.c", {14: "1"})

        adapter = MagicMock()
        adapter.build_system = BuildSystem.MAKE
        adapter.coverage_tool = "gcov"
        adapter.source_directories = ["src"]
        adapter.coverage_command_executes_tests.return_value = False
        adapter.get_execution_commands.return_value = [["make", "test"]]
        adapter.get_build_commands_for_set.return_value = [["make"]]

        def fake_compile(*_args, **_kwargs):
            return CompilationResult(
                success=True,
                binary_path=None,
                error_message=None,
                compilation_time=0.0,
                coverage_enabled=True,
                build_system=BuildSystem.MAKE,
            )

        def fake_coverage(_adapter, _feature, _enabled, **kwargs):
            directory = baseline if kwargs.get("label") == "all_features" else disabled
            return CoverageResult(
                success=True,
                coverage_files=[str(path) for path in directory.iterdir()],
                coverage_dir=str(directory),
                missing_files=[],
                dynamic_execution=True,
                execution_commands=1,
                execution_succeeded=1,
                test_plan_id=kwargs.get("test_plan_id"),
            )

        removal = RemovalResult(
            success=True,
            lines_removed=1,
            files_modified=1,
            files_stubbed=0,
            backup_dir=str(tmp_path / "backup"),
            target_lines=1,
        )
        verification = VerificationResult(
            success=True,
            compiles=True,
            status=VerificationStatus.PASSED,
            total_tests_run=1,
            total_tests_passed=1,
        )
        remove_mock = MagicMock(return_value=removal)
        verify_mock = MagicMock(return_value=verification)

        with patch.multiple(
            "prat.batch",
            discover_features=lambda *args, **kwargs: features,
            compile_with_adapter=fake_compile,
            generate_coverage_with_adapter=fake_coverage,
            build_feature_graph=lambda *args, **kwargs: None,
            generate_feature_graph_html=lambda *args, **kwargs: None,
            capture_reference_outputs=lambda *args, **kwargs: {
                "make test": "ok"
            },
            remove_feature_code=remove_mock,
            verify_correctness=verify_mock,
        ):
            result = run_batch_analysis(
                str(tmp_path),
                output_dir=str(tmp_path),
                adapter=adapter,
                remove=True,
                verify=True,
            )

        assert result.success is True
        assert result.union_removable_lines == 1
        assert result.removal_result is removal
        assert result.verification_result is verification
        assert result.builds_performed == 3
        assert remove_mock.call_args.args[0].file_line_numbers == {
            "src/net.c": [10]
        }
        assert verify_mock.call_args.kwargs["reference_outputs"] == {
            "make test": "ok"
        }
