#!/usr/bin/env python3
"""
Environment setup and dependency verification module for PRAT.

This module handles installation and verification of all required dependencies
including build tools, coverage tools, and Python/Perl packages.
"""

import shutil
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class EnvironmentResult:
    """Result of environment setup or verification operation."""
    success: bool
    available_tools: Dict[str, bool]
    missing_tools: List[str]
    error_message: Optional[str] = None


def verify_dependencies() -> EnvironmentResult:
    """
    Check if required tools are available on the system.
    
    Returns:
        EnvironmentResult with availability status for each tool
    """
    required_tools = {
        # Build tools
        'gcc': 'gcc',
        'clang': 'clang',
        'make': 'make',
        'cmake': 'cmake',
        
        # Coverage tools
        'gcov': 'gcov',
        'llvm-cov-9': 'llvm-cov-9',
        
        # Python
        'python3': 'python3',
        
        # Perl
        'perl': 'perl',
        
        # Optional tools
        'pygmentize': 'pygmentize',
        'xdot': 'xdot',
    }
    
    available_tools = {}
    missing_tools = []
    
    for tool_name, command in required_tools.items():
        is_available = shutil.which(command) is not None
        available_tools[tool_name] = is_available
        
        if not is_available and tool_name not in ['pygmentize', 'xdot']:
            missing_tools.append(tool_name)
    
    # Check Python packages
    python_packages = ['toml', 'pandas']
    for package in python_packages:
        try:
            __import__(package)
            available_tools[f'python-{package}'] = True
        except ImportError:
            available_tools[f'python-{package}'] = False
            missing_tools.append(f'python-{package}')
    
    success = len(missing_tools) == 0
    error_message = None
    
    if not success:
        error_message = f"Missing required dependencies: {', '.join(missing_tools)}"
    
    return EnvironmentResult(
        success=success,
        available_tools=available_tools,
        missing_tools=missing_tools,
        error_message=error_message
    )


def setup_environment() -> EnvironmentResult:
    """
    Install and verify all dependencies.
    
    This function attempts to install missing dependencies using apt-get
    and pip. It requires sudo privileges for system package installation.
    
    Returns:
        EnvironmentResult indicating success or failure of setup
    """
    # First verify what's already available
    initial_check = verify_dependencies()
    
    if initial_check.success:
        return initial_check
    
    print("[+] Setting up PRAT environment...")
    print(f"[+] Missing dependencies: {', '.join(initial_check.missing_tools)}")
    
    # Attempt to install system packages
    system_packages = []
    python_packages = []
    
    for tool in initial_check.missing_tools:
        if tool.startswith('python-'):
            python_packages.append(tool.replace('python-', ''))
        elif tool == 'llvm-cov-9':
            system_packages.append('llvm-9')
        elif tool == 'pygmentize':
            python_packages.append('Pygments')
        else:
            system_packages.append(tool)
    
    # Install system packages
    if system_packages:
        print(f"[+] Installing system packages: {', '.join(system_packages)}")
        try:
            subprocess.run(
                ['sudo', 'apt-get', 'update'],
                check=True,
                capture_output=True
            )
            subprocess.run(
                ['sudo', 'apt-get', 'install', '-y'] + system_packages,
                check=True,
                capture_output=True
            )
        except subprocess.CalledProcessError as e:
            return EnvironmentResult(
                success=False,
                available_tools=initial_check.available_tools,
                missing_tools=initial_check.missing_tools,
                error_message=f"Failed to install system packages: {e}"
            )
    
    # Install Python packages
    if python_packages:
        print(f"[+] Installing Python packages: {', '.join(python_packages)}")
        try:
            subprocess.run(
                ['pip3', 'install'] + python_packages,
                check=True,
                capture_output=True
            )
        except subprocess.CalledProcessError as e:
            return EnvironmentResult(
                success=False,
                available_tools=initial_check.available_tools,
                missing_tools=initial_check.missing_tools,
                error_message=f"Failed to install Python packages: {e}"
            )
    
    # Verify installation was successful
    final_check = verify_dependencies()
    
    if final_check.success:
        print("[+] Environment setup complete!")
    else:
        print(f"[-] Some dependencies could not be installed: {', '.join(final_check.missing_tools)}")
    
    return final_check


def is_tool_available(tool_name: str) -> bool:
    """
    Check if a specific tool is available.
    
    Args:
        tool_name: Name of the tool to check
        
    Returns:
        True if tool is available, False otherwise
    """
    return shutil.which(tool_name) is not None
