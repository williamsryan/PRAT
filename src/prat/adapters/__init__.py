"""
Project adapters for PRAT.

This module provides project-specific adapters that handle build system
differences and project-specific configurations.
"""

from pathlib import Path
from typing import Optional

from .base import ProjectAdapter
from .cmake import CMakeAdapter
from .ffmpeg import FFmpegAdapter
from .mosquitto import MosquittoAdapter
from .rust import RustAdapter

__all__ = [
    'ProjectAdapter',
    'MosquittoAdapter',
    'FFmpegAdapter',
    'RustAdapter',
    'CMakeAdapter',
    'get_adapter',
]


def get_adapter(project_path: str) -> Optional[ProjectAdapter]:
    """
    Auto-detect and return the appropriate adapter for a project.

    Tries project-specific adapters first (Mosquitto, FFmpeg), then
    falls back to generic build-system adapters (CMake, Cargo/Rust).

    Args:
        project_path: Path to project root directory

    Returns:
        A ProjectAdapter instance, or None if no adapter matches.
    """
    Path(project_path)

    # Order matters: specific adapters first, generic ones last.
    adapter_classes = [
        MosquittoAdapter,
        FFmpegAdapter,
        RustAdapter,
        CMakeAdapter,
    ]

    for adapter_cls in adapter_classes:
        adapter = adapter_cls(project_path)
        if adapter.validate_project():
            return adapter

    return None
