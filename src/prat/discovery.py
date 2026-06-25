"""
Feature discovery module for PRAT.

This module provides functions to discover available features in projects
based on their build system configuration files.
"""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .compilation import BuildSystem, detect_build_system


@dataclass
class Feature:
    """Represents a discovered feature."""
    name: str
    description: Optional[str] = None
    default_enabled: Optional[bool] = None


def discover_features(project_path: str) -> list[Feature]:
    """
    Discover available features in a project.

    Automatically detects build system and calls appropriate discovery function.

    Args:
        project_path: Path to project root directory

    Returns:
        List of discovered features
    """
    build_system = detect_build_system(project_path)

    if build_system == BuildSystem.CMAKE:
        return discover_features_cmake(project_path)
    elif build_system == BuildSystem.AUTOTOOLS:
        return discover_features_autotools(project_path)
    elif build_system == BuildSystem.CARGO:
        return discover_features_cargo(project_path)
    elif build_system == BuildSystem.MAKE:
        return discover_features_make(project_path)
    else:
        return []


def discover_features_cmake(project_path: str) -> list[Feature]:
    """
    Discover features in CMake projects by parsing CMakeLists.txt.

    Looks for option() declarations with BOOL type.
    Example: option(CONFIG_TLS "Enable TLS support" ON)

    Args:
        project_path: Path to project root directory

    Returns:
        List of discovered features
    """
    features: list[Feature] = []
    cmake_file = Path(project_path) / "CMakeLists.txt"

    if not cmake_file.exists():
        return features

    try:
        content = cmake_file.read_text()

        # Pattern to match option() declarations
        # option(NAME "description" ON/OFF)
        option_pattern = r'option\s*\(\s*(\w+)\s+["\']([^"\']*)["\'](?:\s+(ON|OFF))?\s*\)'

        for match in re.finditer(option_pattern, content, re.IGNORECASE):
            name = match.group(1)
            description = match.group(2)
            default = match.group(3)

            # Filter for CONFIG_ or WITH_ prefixed options
            if name.startswith(('CONFIG_', 'WITH_', 'ENABLE_')):
                # Remove prefix for cleaner feature name
                clean_name = re.sub(r'^(CONFIG_|WITH_|ENABLE_)', '', name)

                default_enabled = None
                if default:
                    default_enabled = default.upper() == 'ON'

                features.append(Feature(
                    name=clean_name,
                    description=description,
                    default_enabled=default_enabled
                ))

        # Also try running cmake -LA to list cache variables
        try:
            result = subprocess.run(
                ["cmake", "-LA", "-N", "."],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                # Parse cmake -LA output
                for line in result.stdout.splitlines():
                    if ':BOOL=' in line:
                        # Format: NAME:BOOL=ON
                        match = re.match(r'(\w+):BOOL=(ON|OFF)', line)  # type: ignore[assignment]
                        if match:
                            name = match.group(1)
                            value = match.group(2)

                            if name.startswith(('CONFIG_', 'WITH_', 'ENABLE_')):
                                clean_name = re.sub(r'^(CONFIG_|WITH_|ENABLE_)', '', name)

                                # Avoid duplicates
                                if not any(f.name == clean_name for f in features):
                                    features.append(Feature(
                                        name=clean_name,
                                        description=None,
                                        default_enabled=(value == 'ON')
                                    ))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass  # cmake not available or timed out

    except Exception as e:
        print(f"[!] Error parsing CMakeLists.txt: {e}")

    return features


def discover_features_autotools(project_path: str) -> list[Feature]:
    """
    Discover features in Autotools projects by parsing configure --help.

    Looks for --enable-* and --disable-* flags.

    Args:
        project_path: Path to project root directory

    Returns:
        List of discovered features
    """
    features: list[Feature] = []
    configure_script = Path(project_path) / "configure"

    if not configure_script.exists():
        return features

    try:
        # Run configure --help to get available options
        result = subprocess.run(
            ["bash", "configure", "--help"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            return features

        # Parse output for --enable-* and --disable-* flags
        enable_pattern = r'--enable-(\S+)\s+(.+?)(?=\n\s*--|\n\n|\Z)'
        disable_pattern = r'--disable-(\S+)\s+(.+?)(?=\n\s*--|\n\n|\Z)'

        seen_features = set()

        for match in re.finditer(enable_pattern, result.stdout, re.DOTALL):
            name = match.group(1)
            description = match.group(2).strip()

            # Clean up description (remove extra whitespace)
            description = re.sub(r'\s+', ' ', description)

            if name not in seen_features:
                seen_features.add(name)
                features.append(Feature(
                    name=name.upper(),
                    description=description,
                    default_enabled=None  # Can't determine from --help
                ))

        for match in re.finditer(disable_pattern, result.stdout, re.DOTALL):
            name = match.group(1)
            description = match.group(2).strip()

            # Clean up description
            description = re.sub(r'\s+', ' ', description)

            if name not in seen_features:
                seen_features.add(name)
                features.append(Feature(
                    name=name.upper(),
                    description=description,
                    default_enabled=True  # --disable implies default is enabled
                ))

    except subprocess.TimeoutExpired:
        print("[!] configure --help timed out")
    except Exception as e:
        print(f"[!] Error running configure --help: {e}")

    return features


def discover_features_cargo(project_path: str) -> list[Feature]:
    """
    Discover features in Rust projects by parsing Cargo.toml.

    Looks for [features] section.

    Args:
        project_path: Path to project root directory

    Returns:
        List of discovered features
    """
    features: list[Feature] = []
    cargo_toml = Path(project_path) / "Cargo.toml"

    if not cargo_toml.exists():
        return features

    try:
        # Try to use toml library if available
        try:
            import toml  # type: ignore[import-untyped]
            data = toml.load(cargo_toml)

            if 'features' in data:
                for feature_name, dependencies in data['features'].items():
                    # Skip 'default' feature
                    if feature_name == 'default':
                        continue

                    # Create description from dependencies
                    description = f"Enables: {', '.join(dependencies)}" if dependencies else None

                    features.append(Feature(
                        name=feature_name.upper(),
                        description=description,
                        default_enabled=None
                    ))

            # Check if feature is in default features
            if 'features' in data and 'default' in data['features']:
                default_features = set(data['features']['default'])
                for feature in features:
                    if feature.name.lower() in default_features:
                        feature.default_enabled = True

        except ImportError:
            # Fallback: parse manually
            content = cargo_toml.read_text()

            # Find [features] section
            features_match = re.search(
                r'\[features\]\s*\n((?:.*\n)*?)(?:\[|\Z)',
                content,
                re.MULTILINE
            )

            if features_match:
                features_section = features_match.group(1)

                # Parse feature lines: name = ["dep1", "dep2"]
                feature_pattern = r'(\w+)\s*=\s*\[(.*?)\]'

                for match in re.finditer(feature_pattern, features_section):
                    name = match.group(1)
                    deps = match.group(2)

                    if name == 'default':
                        continue

                    description = None
                    if deps.strip():
                        description = f"Enables: {deps}"

                    features.append(Feature(
                        name=name.upper(),
                        description=description,
                        default_enabled=None
                    ))

    except Exception as e:
        print(f"[!] Error parsing Cargo.toml: {e}")

    return features


def discover_features_make(project_path: str) -> list[Feature]:
    """
    Discover features in Make-based projects by parsing Makefile.

    Looks for WITH_* variables and config.mk files.

    Args:
        project_path: Path to project root directory

    Returns:
        List of discovered features
    """
    features: list[Feature] = []
    makefile = Path(project_path) / "Makefile"
    config_mk = Path(project_path) / "config.mk"

    files_to_check = []
    if makefile.exists():
        files_to_check.append(makefile)
    if config_mk.exists():
        files_to_check.append(config_mk)

    if not files_to_check:
        return features

    seen_features = set()

    try:
        for file_path in files_to_check:
            content = file_path.read_text()

            # Look for WITH_* variable definitions
            # Pattern: WITH_FEATURE?=yes or WITH_FEATURE:=yes
            pattern = r'WITH_(\w+)\s*[?:]?=\s*(yes|no)'

            for match in re.finditer(pattern, content, re.IGNORECASE):
                name = match.group(1)
                default_value = match.group(2).lower()

                if name not in seen_features:
                    seen_features.add(name)
                    features.append(Feature(
                        name=name,
                        description=None,
                        default_enabled=(default_value == 'yes')
                    ))

            # Also look for comments describing features
            # Pattern: # WITH_FEATURE - description
            comment_pattern = r'#\s*WITH_(\w+)\s*-\s*(.+)'

            for match in re.finditer(comment_pattern, content):
                name = match.group(1)
                description = match.group(2).strip()

                # Update existing feature or add new one
                existing = next((f for f in features if f.name == name), None)
                if existing:
                    existing.description = description
                elif name not in seen_features:
                    seen_features.add(name)
                    features.append(Feature(
                        name=name,
                        description=description,
                        default_enabled=None
                    ))

    except Exception as e:
        print(f"[!] Error parsing Makefile: {e}")

    return features


def print_features(features: list[Feature], project_name: str = "Project") -> None:
    """
    Print discovered features in a readable format.

    Args:
        features: List of features to print
        project_name: Name of project for display
    """
    if not features:
        print(f"[!] No features discovered for {project_name}")
        return

    print(f"\n[+] Discovered {len(features)} features in {project_name}:")
    print("-" * 70)

    for feature in features:
        print(f"\n  Feature: {feature.name}")

        if feature.description:
            print(f"    Description: {feature.description}")

        if feature.default_enabled is not None:
            default_str = "enabled" if feature.default_enabled else "disabled"
            print(f"    Default: {default_str}")

    print("-" * 70)
