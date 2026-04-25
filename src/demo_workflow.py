#!/usr/bin/env python3
"""
Demo script showing workflow orchestration usage.

This script demonstrates how to use the PRAT workflow module
to run a complete analysis.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from prat.adapters import MosquittoAdapter
from prat.discovery import discover_features, print_features


def demo_feature_discovery():
    """Demonstrate feature discovery."""
    print("\n" + "="*70)
    print("DEMO: Feature Discovery")
    print("="*70)

    project_path = "App/mosquitto"
    features = discover_features(project_path)
    print_features(features, "Mosquitto")


def demo_adapter_usage():
    """Demonstrate adapter pattern."""
    print("\n" + "="*70)
    print("DEMO: Project Adapter")
    print("="*70)

    adapter = MosquittoAdapter("App/mosquitto")

    print("\nProject: Mosquitto")
    print(f"Build System: {adapter.build_system.value}")
    print(f"Coverage Tool: {adapter.coverage_tool}")
    print(f"Source Directories: {', '.join(adapter.source_directories)}")
    print("\nFeature Flag Examples:")
    print(f"  TLS enabled:  {adapter.format_feature_flag('TLS', True)}")
    print(f"  TLS disabled: {adapter.format_feature_flag('TLS', False)}")
    print("\nCompile Command (TLS enabled):")
    print(f"  {' '.join(adapter.get_compile_command('TLS', True))}")
    print(f"\nValidation: {adapter.validate_project()}")


def demo_workflow_info():
    """Show workflow information without running it."""
    print("\n" + "="*70)
    print("DEMO: Workflow Orchestration")
    print("="*70)

    print("\nThe workflow module provides:")
    print("  - run_complete_workflow(): Execute full analysis pipeline")
    print("  - resume_workflow(): Resume from checkpoint after error")
    print("\nWorkflow steps:")
    print("  1. Verify environment dependencies")
    print("  2. Compile with feature enabled")
    print("  3. Generate coverage (enabled)")
    print("  4. Compile with feature disabled")
    print("  5. Generate coverage (disabled)")
    print("  6. Diff coverage files")
    print("  7. Extract features and generate reports")
    print("\nCheckpoints saved at each step for error recovery.")


if __name__ == "__main__":
    demo_feature_discovery()
    demo_adapter_usage()
    demo_workflow_info()

    print("\n" + "="*70)
    print("To run actual workflow:")
    print("  from prat.workflow import run_complete_workflow")
    print("  result = run_complete_workflow('App/mosquitto', 'TLS')")
    print("="*70 + "\n")
