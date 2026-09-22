"""
Cumulative program variants for PRAT's correctness evaluation.

Paper, Correctness: "To keep execution times practical, we did not test all
possible combinations of features; rather, we generated 8 variants of Mosquitto.
We started with a binary that includes all features, which represent variant 0.
This also gives us a baseline for #crashes present in the source prior to feature
removal. We generated variants 1 to 7 in this way: variant i is obtained from
variant i-1 by selecting and deactivating a feature that was active in variant i."

This is a *chain*, not a star. It differs from the mapping in
:mod:`prat.batch`, where every feature is isolated against the same
all-features baseline: here each variant keeps the previous variant's removals
and adds one more. The chain is what tests feature *interaction* — whether
removing TLS and then Bridge breaks something that removing either alone does
not — which is the property the paper's fuzzing table is evidence for.

Each variant is produced by mapping the next feature against the *current*
variant's coverage, then removing it. Mapping against the current state rather
than against the original all-features build matters: after TLS is gone, the code
attributable to TLS_PSK is different, and reusing the original D_f would try to
remove lines that are already gone.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from .adapters import ProjectAdapter, get_adapter
from .compilation import BuildSystem, compile_with_adapter
from .coverage import generate_coverage_with_adapter
from .discovery import discover_features
from .extraction import ExtractionResult, extract_from_mapping
from .gcov import load_coverage_dir
from .mapping import FeatureMapping, map_feature_from_coverage
from .mapping import protected_lines as mapping_protected
from .removal import RemovalResult, remove_feature_code


@dataclass
class Variant:
    """One link in the cumulative chain."""

    index: int
    label: str
    #: Every feature removed up to and including this variant.
    removed_features: list[str] = field(default_factory=list)
    #: The feature removed to get here from the previous variant (None for 0).
    newly_removed: str | None = None

    mapping: FeatureMapping | None = None
    extraction: ExtractionResult | None = None
    removal: RemovalResult | None = None

    binary_path: str | None = None
    coverage_dir: str | None = None

    lines_removed: int = 0
    build_time: float = 0.0
    success: bool = False
    error_message: str | None = None


@dataclass
class VariantChain:
    """The full chain, variant 0 first."""

    project: str
    variants: list[Variant] = field(default_factory=list)
    total_time: float = 0.0
    error_message: str | None = None

    @property
    def success(self) -> bool:
        return bool(self.variants) and all(v.success for v in self.variants)

    @property
    def baseline(self) -> Variant | None:
        return self.variants[0] if self.variants else None

    def summary(self) -> str:
        lines = [
            f"Variant chain for {self.project}",
            f"{'Variant':<10} {'Removed feature':<24} {'Cumulative':<11} {'Lines':>8}",
            "-" * 58,
        ]
        for variant in self.variants:
            lines.append(
                f"{variant.label:<10} "
                f"{(variant.newly_removed or '(baseline)'):<24} "
                f"{len(variant.removed_features):<11} "
                f"{variant.lines_removed:>8}"
            )
        return "\n".join(lines)


def _snapshot_binary(
    binary_path: str | None,
    output_dir: str,
    label: str,
) -> str | None:
    """Copy a variant binary to immutable per-variant storage."""
    if not binary_path:
        return None
    source = Path(binary_path)
    if not source.is_file():
        return None
    destination_dir = Path(output_dir) / "variant_binaries" / label
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name
    shutil.copy2(source, destination)
    return str(destination)


def build_variant_chain(
    project_path: str,
    features: list[str] | None = None,
    variant_count: int = 8,
    output_dir: str | None = None,
    adapter: ProjectAdapter | None = None,
    build_system: BuildSystem | None = None,
    run_tests: bool = False,
    symbolic_tests: list[str] | None = None,
    apply_removal: bool = True,
) -> VariantChain:
    """Generate the paper's cumulative variant chain.

    Variant 0 is the all-features build. Variant *i* takes variant *i-1* and
    additionally removes one feature that was still active.

    Args:
        project_path: Project root. This tree is *modified* when
            ``apply_removal`` is set, since each variant builds on the last.
        features: Removal order. Defaults to discovered features sorted by name
            for determinism.
        variant_count: Total variants including the baseline (the paper uses 8).
        output_dir: Directory for coverage and per-variant artifacts.
        adapter: ProjectAdapter (auto-detected if None).
        build_system: Build system override.
        run_tests: Run the project's test suite during compilation.
        symbolic_tests: KLEE ``.ktest`` paths to include in T.
        apply_removal: Actually remove the code. With False, the chain is
            computed and reported but the tree is left untouched, which is useful
            for previewing the order.

    Returns:
        VariantChain with one entry per variant.
    """
    start = time.time()
    project_name = Path(project_path).name
    chain = VariantChain(project=project_name)

    if output_dir is None:
        output_dir = project_path

    if adapter is None:
        adapter = get_adapter(project_path)

    if adapter is None:
        chain.error_message = (
            "No project adapter available; the variant chain needs one to build "
            "an explicit feature set per variant"
        )
        chain.total_time = time.time() - start
        return chain

    if features is None:
        discovered = discover_features(project_path, adapter=adapter)
        features = [feature.name for feature in discovered]

    if not features:
        chain.error_message = "No features available to build a variant chain"
        chain.total_time = time.time() - start
        return chain

    # variant_count includes variant 0, so at most variant_count-1 removals.
    removal_order = features[: max(0, variant_count - 1)]

    print(f"\n{'=' * 70}")
    print(f"PRAT variant chain: {project_name}")
    print(f"{'=' * 70}")
    print(f"Variants: {len(removal_order) + 1} (0 = all features)")
    print(f"Removal order: {', '.join(removal_order)}\n")

    all_states = {name: True for name in features}
    removed: list[str] = []

    # --- Variant 0: all features enabled -----------------------------------
    print(f"{'-' * 50}")
    print("[variant_0] all features enabled (baseline)")
    print(f"{'-' * 50}")

    baseline = Variant(index=0, label="variant_0")
    variant_start = time.time()

    compilation = compile_with_adapter(
        adapter, features[0], True, run_tests, feature_states=dict(all_states)
    )

    if not compilation.success:
        baseline.error_message = compilation.error_message
        baseline.build_time = time.time() - variant_start
        chain.variants.append(baseline)
        chain.error_message = f"Baseline build failed: {baseline.error_message}"
        chain.total_time = time.time() - start
        print(f"    [!] {chain.error_message}")
        return chain

    coverage = generate_coverage_with_adapter(
        adapter, features[0], True,
        output_dir=output_dir,
        symbolic_tests=symbolic_tests or None,
        feature_states=dict(all_states),
        label="variant_0",
    )

    baseline.binary_path = _snapshot_binary(
        compilation.binary_path, output_dir, baseline.label
    )
    baseline.coverage_dir = coverage.coverage_dir if coverage.success else None
    baseline.build_time = time.time() - variant_start
    baseline.success = coverage.success
    if not coverage.success:
        baseline.error_message = coverage.error_message
        print(f"    [!] Baseline coverage failed: {coverage.error_message}")
    else:
        print(f"    Built and instrumented ({baseline.build_time:.1f}s)")

    chain.variants.append(baseline)

    if not baseline.success:
        chain.error_message = "Baseline coverage unavailable; cannot chain"
        chain.total_time = time.time() - start
        return chain
    current_coverage_dir = baseline.coverage_dir

    # --- Variants 1..N: cumulative removal ---------------------------------
    for index, feature in enumerate(removal_order, start=1):
        label = f"variant_{index}"
        print(f"\n{'-' * 50}")
        print(f"[{label}] additionally remove {feature}")
        print(f"{'-' * 50}")

        variant = Variant(
            index=index,
            label=label,
            newly_removed=feature,
            removed_features=[*removed, feature],
        )
        variant_start = time.time()

        # Build the same variant with this one feature additionally disabled.
        states = dict(all_states)
        for already in variant.removed_features:
            states[already] = False

        compilation = compile_with_adapter(
            adapter, feature, False, run_tests, feature_states=states
        )

        if not compilation.success:
            variant.error_message = compilation.error_message
            variant.build_time = time.time() - variant_start
            chain.variants.append(variant)
            print(f"    [!] Build failed, stopping chain: "
                  f"{(variant.error_message or '').splitlines()[:1]}")
            break

        coverage = generate_coverage_with_adapter(
            adapter, feature, False,
            output_dir=output_dir,
            symbolic_tests=symbolic_tests or None,
            feature_states=states,
            label=label,
        )

        if not coverage.success:
            variant.error_message = coverage.error_message
            variant.build_time = time.time() - variant_start
            chain.variants.append(variant)
            print(f"    [!] Coverage failed, stopping chain: {coverage.error_message}")
            break

        # D_f against the *current* variant, not the original baseline.
        mapping = map_feature_from_coverage(
            feature,
            load_coverage_dir(current_coverage_dir or ""),
            load_coverage_dir(coverage.coverage_dir),
        )
        extraction = extract_from_mapping(mapping)

        variant.mapping = mapping
        variant.extraction = extraction
        variant.lines_removed = extraction.total_removable_lines
        variant.coverage_dir = coverage.coverage_dir

        print(f"    |D_f| = {extraction.total_removable_lines} line(s) across "
              f"{len(extraction.file_line_counts)} file(s)")

        if apply_removal and extraction.total_removable_lines:
            variant.removal = remove_feature_code(
                extraction,
                project_path,
                feature,
                protected_lines=mapping_protected(mapping),
                rebuild=True,
                build_commands=adapter.get_build_commands_for_set(
                    states, with_coverage=False
                ),
            )
            if not variant.removal.success:
                variant.error_message = variant.removal.error_message
                variant.build_time = time.time() - variant_start
                chain.variants.append(variant)
                print(f"    [!] Removal failed, stopping chain: "
                      f"{variant.error_message}")
                break
            print(f"    Removed {variant.removal.lines_removed} line(s)")

        variant.binary_path = _snapshot_binary(
            adapter.get_binary_path() if apply_removal else compilation.binary_path,
            output_dir,
            label,
        )
        variant.build_time = time.time() - variant_start
        variant.success = True
        chain.variants.append(variant)

        removed = list(variant.removed_features)
        current_coverage_dir = coverage.coverage_dir

    chain.total_time = time.time() - start

    print(f"\n{'=' * 70}")
    print(chain.summary())
    print(f"\nTotal time: {chain.total_time:.1f}s")
    print(f"{'=' * 70}\n")

    return chain
