"""
Base project adapter for PRAT.

Defines the common interface that all project adapters must implement.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict
from pathlib import Path

from ..compilation import BuildSystem, CompilationResult


class ProjectAdapter(ABC):
    """
    Abstract base class for project-specific adapters.
    
    Each adapter encapsulates project-specific details like build commands,
    feature flag formats, source directories, and coverage tool preferences.
    """
    
    def __init__(self, project_path: str):
        """
        Initialize adapter with project path.
        
        Args:
            project_path: Path to project root directory
        """
        self.project_path = Path(project_path)
    
    @property
    @abstractmethod
    def build_system(self) -> BuildSystem:
        """Return the build system used by this project."""
        pass
    
    @property
    @abstractmethod
    def coverage_tool(self) -> str:
        """Return the preferred coverage tool (gcov, llvm-cov, etc.)."""
        pass
    
    @property
    @abstractmethod
    def source_directories(self) -> List[str]:
        """Return list of source directories to analyze."""
        pass
    
    @abstractmethod
    def get_compile_command(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True
    ) -> List[str]:
        """
        Get compilation command for this project.
        
        Args:
            feature: Feature name to enable/disable
            enabled: True to enable feature, False to disable
            with_coverage: Whether to enable coverage instrumentation
            
        Returns:
            List of command arguments to execute
        """
        pass
    
    @abstractmethod
    def get_clean_command(self) -> List[str]:
        """
        Get clean command to remove build artifacts.
        
        Returns:
            List of command arguments to execute
        """
        pass
    
    @abstractmethod
    def get_test_command(self) -> Optional[List[str]]:
        """
        Get test command to run test suite.
        
        Returns:
            List of command arguments, or None if no tests available
        """
        pass
    
    @abstractmethod
    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        """
        Format feature flag in project-specific format.
        
        Args:
            feature: Feature name
            enabled: True to enable, False to disable
            
        Returns:
            Formatted feature flag string
        """
        pass
    
    def get_binary_path(self) -> Optional[str]:
        """
        Get path to compiled binary.
        
        Returns:
            Path to binary, or None if not applicable
        """
        return None
    
    def get_coverage_environment(self) -> Dict[str, str]:
        """
        Get environment variables needed for coverage.
        
        Returns:
            Dictionary of environment variables
        """
        return {}
    
    def validate_project(self) -> bool:
        """
        Validate that this adapter is appropriate for the project.
        
        Returns:
            True if project structure matches adapter expectations
        """
        return self.project_path.exists()
