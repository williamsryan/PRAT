"""
Project adapters for PRAT.

This module provides project-specific adapters that handle build system
differences and project-specific configurations.
"""

from .base import ProjectAdapter
from .mosquitto import MosquittoAdapter
from .ffmpeg import FFmpegAdapter
from .rust import RustAdapter
from .cmake import CMakeAdapter

__all__ = [
    'ProjectAdapter',
    'MosquittoAdapter',
    'FFmpegAdapter',
    'RustAdapter',
    'CMakeAdapter',
]
