"""
Mosquitto project adapter for PRAT.

Handles Make-based builds with WITH_FEATURE=yes/no flags.
"""

import os
from typing import List, Optional, Dict
from pathlib import Path

from ..compilation import BuildSystem
from .base import ProjectAdapter


class MosquittoAdapter(ProjectAdapter):
    """
    Adapter for Mosquitto MQTT broker.
    
    Build system: Make
    Feature format: WITH_FEATURE=yes/no
    Coverage tool: llvm-cov-9
    """
    
    @property
    def build_system(self) -> BuildSystem:
        """Mosquitto uses Make."""
        return BuildSystem.MAKE
    
    @property
    def coverage_tool(self) -> str:
        """Mosquitto prefers llvm-cov-9."""
        return "llvm-cov-9"
    
    @property
    def source_directories(self) -> List[str]:
        """Mosquitto source directories."""
        return ["src", "lib"]
    
    def get_compile_command(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True
    ) -> List[str]:
        """
        Get Make compilation command for Mosquitto.
        
        Example: make binary -j WITH_COVERAGE=yes WITH_TLS=yes
        """
        cmd = ["make", "binary", "-j"]
        
        if with_coverage:
            cmd.append("WITH_COVERAGE=yes")
        
        # Add feature flag
        flag = self.format_feature_flag(feature, enabled)
        cmd.append(flag)
        
        return cmd
    
    def get_clean_command(self) -> List[str]:
        """Get Make clean command."""
        return ["make", "clean"]
    
    def get_test_command(self) -> Optional[List[str]]:
        """Get Mosquitto test command."""
        return ["make", "utest", "-j", "WITH_COVERAGE=yes"]
    
    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        """
        Format feature flag as WITH_FEATURE=yes/no.
        
        Args:
            feature: Feature name (e.g., "TLS", "BRIDGE")
            enabled: True for yes, False for no
            
        Returns:
            Formatted flag like "WITH_TLS=yes"
        """
        flag_value = "yes" if enabled else "no"
        return f"WITH_{feature.upper()}={flag_value}"
    
    def get_binary_path(self) -> Optional[str]:
        """Get path to mosquitto binary."""
        binary = self.project_path / "src" / "mosquitto"
        if binary.exists():
            return str(binary)
        return None
    
    def validate_project(self) -> bool:
        """Validate this is a Mosquitto project."""
        # Check for Mosquitto-specific files
        makefile = self.project_path / "Makefile"
        config_mk = self.project_path / "config.mk"
        src_dir = self.project_path / "src"
        
        return (
            makefile.exists() and
            config_mk.exists() and
            src_dir.exists()
        )
