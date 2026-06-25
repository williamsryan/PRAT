"""
Project adapters for PRAT.

This module provides project-specific adapters that handle build system
differences and project-specific configurations.
"""

from pathlib import Path
from typing import Optional

from .aom import AomAdapter
from .base import ProjectAdapter
from .cmake import CMakeAdapter
from .ffmpeg import FFmpegAdapter
from .mosquitto import MosquittoAdapter
from .opendds import OpenDDSAdapter
from .rust import RustAdapter
from .uamqp import UamqpAdapter

__all__ = [
    'ProjectAdapter',
    'MosquittoAdapter',
    'FFmpegAdapter',
    'RustAdapter',
    'CMakeAdapter',
    'UamqpAdapter',
    'OpenDDSAdapter',
    'AomAdapter',
    'get_adapter',
]


def get_adapter(project_path: str) -> Optional[ProjectAdapter]:
    """
    Auto-detect and return the appropriate adapter for a project.

    Tries project-specific adapters first (Mosquitto, FFmpeg, azure-uamqp-c,
    OpenDDS, AOM), then falls back to generic build-system adapters (CMake,
    Cargo/Rust).

    Args:
        project_path: Path to project root directory

    Returns:
        A ProjectAdapter instance, or None if no adapter matches.
    """
    Path(project_path)

    # Order matters: specific adapters first, generic ones last.
    adapter_classes: list[type[ProjectAdapter]] = [
        MosquittoAdapter,
        FFmpegAdapter,
        UamqpAdapter,
        OpenDDSAdapter,
        AomAdapter,
        RustAdapter,
        CMakeAdapter,
    ]

    for adapter_cls in adapter_classes:
        adapter = adapter_cls(project_path)  # type: ignore[abstract]
        if adapter.validate_project():
            return adapter

    return None
