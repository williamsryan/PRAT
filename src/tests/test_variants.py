"""Tests for prat.variants — the paper's cumulative variant chain.

"variant i is obtained from variant i-1 by selecting and deactivating a feature
that was active in variant i" — a chain, not the star topology used for mapping.
"""

from unittest.mock import patch

from prat.compilation import BuildSystem, CompilationResult
from prat.coverage import CoverageResult
from prat.discovery import Feature
from prat.removal import RemovalResult
from prat.variants import VariantChain, build_variant_chain

from .test_mapping import write_gcov


def make_feature(name):
    return Feature(name=name, raw_name=name)


def ok_compilation():
    return CompilationResult(
        success=True, binary_path="/fake/bin", error_message=None,
        compilation_time=0.0, coverage_enabled=True,
        build_system=BuildSystem.MAKE,
    )


class ChainHarness:
    """Records the feature states each build was asked for."""

    def __init__(self, tmp_path, features, coverage_by_label):
        self.tmp_path = tmp_path
        self.features = features
        self.coverage_by_label = coverage_by_label
        self.builds = []

    def compile(self, adapter, feature, enabled, run_tests, feature_states=None):
        self.builds.append(dict(feature_states or {}))
        return ok_compilation()

    def coverage(self, adapter, feature, enabled, **kwargs):
        label = kwargs.get("label") or "variant_0"
        directory = self.coverage_by_label[label]
        return CoverageResult(
            success=True,
            coverage_files=[str(p) for p in directory.iterdir()],
            coverage_dir=str(directory),
            missing_files=[],
        )

    def patches(self):
        return patch.multiple(
            "prat.variants",
            discover_features=lambda *a, **k: self.features,
            get_adapter=lambda *a, **k: object(),
            compile_with_adapter=self.compile,
            generate_coverage_with_adapter=self.coverage,
        )


class TestBuildVariantChain:
    def test_removal_is_cumulative_across_variants(self, tmp_path):
        features = [make_feature("TLS"), make_feature("BRIDGE")]

        v0 = tmp_path / "v0"
        write_gcov(v0, "src/net.c", {10: "1", 11: "1", 14: "9"})
        v1 = tmp_path / "v1"
        write_gcov(v1, "src/net.c", {11: "1", 14: "9"})
        v2 = tmp_path / "v2"
        write_gcov(v2, "src/net.c", {14: "9"})

        harness = ChainHarness(
            tmp_path, features,
            {"variant_0": v0, "variant_1": v1, "variant_2": v2},
        )

        with harness.patches():
            chain = build_variant_chain(
                str(tmp_path), variant_count=3,
                output_dir=str(tmp_path), apply_removal=False,
            )

        labels = [v.label for v in chain.variants]
        assert labels == ["variant_0", "variant_1", "variant_2"]
        # Each variant keeps the previous removals and adds one.
        assert chain.variants[0].removed_features == []
        assert chain.variants[1].removed_features == ["TLS"]
        assert chain.variants[2].removed_features == ["TLS", "BRIDGE"]

    def test_each_build_disables_everything_removed_so_far(self, tmp_path):
        features = [make_feature("TLS"), make_feature("BRIDGE")]

        v0 = tmp_path / "v0"
        write_gcov(v0, "src/net.c", {10: "1", 11: "1"})
        v1 = tmp_path / "v1"
        write_gcov(v1, "src/net.c", {11: "1"})
        v2 = tmp_path / "v2"
        write_gcov(v2, "src/net.c", {})

        harness = ChainHarness(
            tmp_path, features,
            {"variant_0": v0, "variant_1": v1, "variant_2": v2},
        )

        with harness.patches():
            build_variant_chain(
                str(tmp_path), variant_count=3,
                output_dir=str(tmp_path), apply_removal=False,
            )

        assert harness.builds[0] == {"TLS": True, "BRIDGE": True}
        assert harness.builds[1] == {"TLS": False, "BRIDGE": True}
        # Variant 2 keeps TLS off as well — this is the chain property.
        assert harness.builds[2] == {"TLS": False, "BRIDGE": False}

    def test_maps_against_the_previous_variant_not_the_baseline(self, tmp_path):
        """After TLS is gone, BRIDGE's footprint is measured against variant 1."""
        features = [make_feature("TLS"), make_feature("BRIDGE")]

        v0 = tmp_path / "v0"
        write_gcov(v0, "src/net.c", {10: "1", 11: "1", 14: "9"})
        v1 = tmp_path / "v1"
        write_gcov(v1, "src/net.c", {11: "1", 14: "9"})
        v2 = tmp_path / "v2"
        write_gcov(v2, "src/net.c", {14: "9"})

        harness = ChainHarness(
            tmp_path, features,
            {"variant_0": v0, "variant_1": v1, "variant_2": v2},
        )

        with harness.patches():
            chain = build_variant_chain(
                str(tmp_path), variant_count=3,
                output_dir=str(tmp_path), apply_removal=False,
            )

        # variant_1 removes line 10 (v0 \ v1); variant_2 removes line 11
        # (v1 \ v2), not lines 10 and 11.
        assert chain.variants[1].extraction.file_line_numbers == {"src/net.c": [10]}
        assert chain.variants[2].extraction.file_line_numbers == {"src/net.c": [11]}

    def test_variant_count_caps_the_chain_length(self, tmp_path):
        features = [make_feature(f"F{i}") for i in range(10)]

        directories = {}
        for index in range(4):
            directory = tmp_path / f"v{index}"
            write_gcov(directory, "src/net.c", {1: "1"})
            directories[f"variant_{index}"] = directory

        harness = ChainHarness(tmp_path, features, directories)

        with harness.patches():
            chain = build_variant_chain(
                str(tmp_path), variant_count=4,
                output_dir=str(tmp_path), apply_removal=False,
            )

        assert len(chain.variants) == 4

    def test_explicit_removal_order_is_honoured(self, tmp_path):
        features = [make_feature("TLS"), make_feature("BRIDGE")]

        directories = {}
        for index in range(3):
            directory = tmp_path / f"v{index}"
            write_gcov(directory, "src/net.c", {1: "1"})
            directories[f"variant_{index}"] = directory

        harness = ChainHarness(tmp_path, features, directories)

        with harness.patches():
            chain = build_variant_chain(
                str(tmp_path), features=["BRIDGE", "TLS"], variant_count=3,
                output_dir=str(tmp_path), apply_removal=False,
            )

        assert chain.variants[1].newly_removed == "BRIDGE"
        assert chain.variants[2].newly_removed == "TLS"

    def test_applies_removal_when_requested(self, tmp_path):
        features = [make_feature("TLS")]

        v0 = tmp_path / "v0"
        write_gcov(v0, "src/net.c", {10: "1", 14: "9"})
        v1 = tmp_path / "v1"
        write_gcov(v1, "src/net.c", {14: "9"})

        harness = ChainHarness(
            tmp_path, features, {"variant_0": v0, "variant_1": v1}
        )
        removal = RemovalResult(
            success=True, lines_removed=1, files_modified=1, files_stubbed=0
        )

        with harness.patches(), patch(
            "prat.variants.remove_feature_code", return_value=removal
        ) as remove:
            chain = build_variant_chain(
                str(tmp_path), variant_count=2,
                output_dir=str(tmp_path), apply_removal=True,
            )

        remove.assert_called_once()
        assert chain.variants[1].removal.lines_removed == 1

    def test_failed_removal_stops_the_chain(self, tmp_path):
        features = [make_feature("TLS"), make_feature("BRIDGE")]

        v0 = tmp_path / "v0"
        write_gcov(v0, "src/net.c", {10: "1", 14: "9"})
        v1 = tmp_path / "v1"
        write_gcov(v1, "src/net.c", {14: "9"})
        v2 = tmp_path / "v2"
        write_gcov(v2, "src/net.c", {14: "9"})

        harness = ChainHarness(
            tmp_path, features,
            {"variant_0": v0, "variant_1": v1, "variant_2": v2},
        )
        failed = RemovalResult(
            success=False, lines_removed=0, files_modified=0, files_stubbed=0,
            error_message="rebuild failed",
        )

        with harness.patches(), patch(
            "prat.variants.remove_feature_code", return_value=failed
        ):
            chain = build_variant_chain(
                str(tmp_path), variant_count=3,
                output_dir=str(tmp_path), apply_removal=True,
            )

        # The chain cannot continue from a broken variant.
        assert len(chain.variants) == 2
        assert chain.success is False

    def test_no_features_is_reported_cleanly(self, tmp_path):
        with patch.multiple(
            "prat.variants",
            discover_features=lambda *a, **k: [],
            get_adapter=lambda *a, **k: object(),
        ):
            chain = build_variant_chain(str(tmp_path))

        assert chain.success is False
        assert "No features" in (chain.error_message or "")

    def test_missing_adapter_is_reported_cleanly(self, tmp_path):
        with patch("prat.variants.get_adapter", return_value=None):
            chain = build_variant_chain(str(tmp_path))

        assert chain.success is False
        assert "adapter" in (chain.error_message or "")

    def test_baseline_build_failure_is_reported(self, tmp_path):
        features = [make_feature("TLS")]
        failure = CompilationResult(
            success=False, binary_path=None, error_message="boom",
            compilation_time=0.0, coverage_enabled=True,
            build_system=BuildSystem.MAKE,
        )

        with patch.multiple(
            "prat.variants",
            discover_features=lambda *a, **k: features,
            get_adapter=lambda *a, **k: object(),
            compile_with_adapter=lambda *a, **k: failure,
        ):
            chain = build_variant_chain(str(tmp_path), output_dir=str(tmp_path))

        assert chain.success is False
        assert "Baseline build failed" in (chain.error_message or "")


class TestVariantChain:
    def test_summary_lists_every_variant(self):
        from prat.variants import Variant

        chain = VariantChain(project="mosquitto", variants=[
            Variant(index=0, label="variant_0", success=True),
            Variant(index=1, label="variant_1", newly_removed="TLS",
                    removed_features=["TLS"], lines_removed=790, success=True),
        ])

        summary = chain.summary()

        assert "(baseline)" in summary
        assert "TLS" in summary
        assert "790" in summary

    def test_success_requires_every_variant_to_succeed(self):
        from prat.variants import Variant

        chain = VariantChain(project="p", variants=[
            Variant(index=0, label="variant_0", success=True),
            Variant(index=1, label="variant_1", success=False),
        ])

        assert chain.success is False
