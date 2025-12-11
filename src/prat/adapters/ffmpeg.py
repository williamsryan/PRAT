"""
FFmpeg project adapter for PRAT.

Handles Autotools-based builds with --enable/--disable flags.
"""

from typing import List, Optional, Dict
from pathlib import Path

from ..compilation import BuildSystem
from .base import ProjectAdapter


class FFmpegAdapter(ProjectAdapter):
    """
    Adapter for FFmpeg multimedia framework.
    
    Build system: Autotools (configure)
    Feature format: --enable-feature / --disable-feature
    Coverage tool: gcov
    """
    
    @property
    def build_system(self) -> BuildSystem:
        """FFmpeg uses Autotools."""
        return BuildSystem.AUTOTOOLS
    
    @property
    def coverage_tool(self) -> str:
        """FFmpeg uses gcov."""
        return "gcov"
    
    @property
    def source_directories(self) -> List[str]:
        """FFmpeg source directories."""
        return [
            "libavcodec",
            "libavfilter",
            "libavformat",
            "libavutil",
            "libswresample",
            "libswscale"
        ]
    
    def get_compile_command(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True
    ) -> List[str]:
        """
        Get configure + make commands for FFmpeg.
        
        Note: This returns the configure command. Make must be run separately.
        Example: bash configure --toolchain=gcov --disable-decoder=h264
        """
        cmd = ["bash", "configure"]
        
        if with_coverage:
            cmd.append("--toolchain=gcov")
        
        # Add feature flag
        if not enabled:
            # FFmpeg uses --disable-feature format
            flag = self.format_feature_flag(feature, enabled)
            cmd.append(flag)
        # If enabled, most features are on by default
        
        return cmd
    
    def get_clean_command(self) -> List[str]:
        """Get Make clean command."""
        return ["make", "clean"]
    
    def get_test_command(self) -> Optional[List[str]]:
        """Get FFmpeg test command (FATE test suite)."""
        return ["make", "fate", "-j3", "SAMPLES=fate-suite/"]
    
    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        """
        Format feature flag as --enable-feature or --disable-feature.
        
        Args:
            feature: Feature name (e.g., "decoder", "encoder", "protocol")
            enabled: True for --enable, False for --disable
            
        Returns:
            Formatted flag like "--disable-decoder"
        """
        prefix = "--enable" if enabled else "--disable"
        return f"{prefix}-{feature.lower()}"
    
    def get_binary_path(self) -> Optional[str]:
        """Get path to FFmpeg binaries."""
        # FFmpeg builds multiple binaries
        ffmpeg_bin = self.project_path / "ffmpeg"
        if ffmpeg_bin.exists():
            return str(ffmpeg_bin)
        return str(self.project_path)
    
    def validate_project(self) -> bool:
        """Validate this is an FFmpeg project."""
        # Check for FFmpeg-specific files
        configure = self.project_path / "configure"
        libavcodec = self.project_path / "libavcodec"
        
        return configure.exists() and libavcodec.exists()
    
    def get_make_command(self) -> List[str]:
        """
        Get make command to run after configure.
        
        Returns:
            Make command with parallel jobs
        """
        return ["make", "-j3"]
