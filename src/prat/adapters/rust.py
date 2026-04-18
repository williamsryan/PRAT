"""
Rust project adapter for PRAT.

Handles Cargo-based builds with --features flags.
"""

from typing import Dict, List, Optional

from ..compilation import BuildSystem
from .base import ProjectAdapter


class RustAdapter(ProjectAdapter):
    """
    Adapter for Rust projects using Cargo.
    
    Build system: Cargo
    Feature format: --features feature / --no-default-features
    Coverage tool: gcov-9 (via grcov)
    """

    @property
    def build_system(self) -> BuildSystem:
        """Rust projects use Cargo."""
        return BuildSystem.CARGO

    @property
    def coverage_tool(self) -> str:
        """Rust uses gcov-9 with grcov."""
        return "gcov-9"

    @property
    def source_directories(self) -> List[str]:
        """Rust source directories."""
        return ["src"]

    def get_compile_command(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True
    ) -> List[str]:
        """
        Get Cargo build command.
        
        Example: cargo build --features tls
        Example: cargo build --no-default-features
        """
        cmd = ["cargo", "build"]

        if enabled:
            cmd.extend(["--features", feature.lower()])
        else:
            cmd.append("--no-default-features")

        return cmd

    def get_clean_command(self) -> List[str]:
        """Get Cargo clean command."""
        return ["cargo", "clean"]

    def get_test_command(self) -> Optional[List[str]]:
        """Get Cargo test command."""
        return ["cargo", "test"]

    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        """
        Format feature flag for Cargo.
        
        Args:
            feature: Feature name
            enabled: True for --features, False for --no-default-features
            
        Returns:
            Formatted flag
        """
        if enabled:
            return f"--features {feature.lower()}"
        else:
            return "--no-default-features"

    def get_binary_path(self) -> Optional[str]:
        """Get path to Cargo target directory."""
        target_dir = self.project_path / "target" / "debug"
        if target_dir.exists():
            return str(target_dir)
        return None

    def get_coverage_environment(self) -> Dict[str, str]:
        """
        Get environment variables for Rust coverage.
        
        Returns:
            Environment variables for coverage instrumentation
        """
        return {
            "CARGO_INCREMENTAL": "0",
            "RUSTFLAGS": "-Zprofile -Ccodegen-units=1 -Copt-level=0 "
                        "-Clink-dead-code -Coverflow-checks=off "
                        "-Zpanic_abort_tests -Cpanic=abort",
            "RUSTDOCFLAGS": "-Cpanic=abort"
        }

    def validate_project(self) -> bool:
        """Validate this is a Rust project."""
        cargo_toml = self.project_path / "Cargo.toml"
        src_dir = self.project_path / "src"

        return cargo_toml.exists() and src_dir.exists()
