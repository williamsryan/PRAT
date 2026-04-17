"""
Coverage diff module for PRAT.

This module handles comparing coverage files between feature-enabled and
feature-disabled builds to identify feature-specific code.
"""

import os
import subprocess
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict


@dataclass
class DiffResult:
    """Result of coverage diff operation."""
    success: bool
    diff_dir: str
    diff_files: List[str]
    feature_only_files: List[str]
    total_diffs: int
    error_message: Optional[str] = None


def match_coverage_files(dir1: str, dir2: str) -> List[Tuple[str, str]]:
    """
    Match coverage files by base name between two directories.
    
    Args:
        dir1: First coverage directory
        dir2: Second coverage directory
    
    Returns:
        List of (file1_path, file2_path) tuples for matching files
    """
    if not os.path.exists(dir1):
        return []
    if not os.path.exists(dir2):
        return []
    
    # Get base names (without extension) from both directories
    files1 = {os.path.splitext(f)[0]: f for f in os.listdir(dir1) 
              if os.path.isfile(os.path.join(dir1, f))}
    files2 = {os.path.splitext(f)[0]: f for f in os.listdir(dir2) 
              if os.path.isfile(os.path.join(dir2, f))}
    
    # Find matching base names
    matching_bases = set(files1.keys()) & set(files2.keys())
    
    # Create tuples of full paths
    matches = []
    for base in matching_bases:
        file1_path = os.path.join(dir1, files1[base])
        file2_path = os.path.join(dir2, files2[base])
        matches.append((file1_path, file2_path))
    
    return matches


def diff_coverage_files(enabled_dir: str, disabled_dir: str, 
                       feature: str,
                       output_dir: Optional[str] = None) -> DiffResult:
    """
    Generate unified diffs between matching coverage files.
    
    Args:
        enabled_dir: Directory with feature-enabled coverage
        disabled_dir: Directory with feature-disabled coverage
        feature: Feature name for output directory naming
        output_dir: Base directory for diff output (default: current directory)
    
    Returns:
        DiffResult with paths to diff files and statistics
    """
    print(f"[+] Checking for matching files in {enabled_dir} and {disabled_dir}")
    
    # Validate input directories
    if not os.path.exists(enabled_dir):
        return DiffResult(
            success=False,
            diff_dir="",
            diff_files=[],
            feature_only_files=[],
            total_diffs=0,
            error_message=f"Enabled directory does not exist: {enabled_dir}"
        )
    
    if not os.path.exists(disabled_dir):
        return DiffResult(
            success=False,
            diff_dir="",
            diff_files=[],
            feature_only_files=[],
            total_diffs=0,
            error_message=f"Disabled directory does not exist: {disabled_dir}"
        )
    
    # Create output directory
    base_dir = output_dir if output_dir else os.getcwd()
    outdir = os.path.join(base_dir, f"diff_{feature}")
    os.makedirs(outdir, exist_ok=True)

    # Create reports directory alongside diff output
    reports_dir = os.path.join(base_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    
    # Match files between directories
    matches = match_coverage_files(enabled_dir, disabled_dir)
    
    # Track feature-only files
    enabled_files = {os.path.splitext(f)[0] for f in os.listdir(enabled_dir) 
                     if os.path.isfile(os.path.join(enabled_dir, f))}
    disabled_files = {os.path.splitext(f)[0] for f in os.listdir(disabled_dir) 
                      if os.path.isfile(os.path.join(disabled_dir, f))}
    feature_only = enabled_files - disabled_files
    
    # Report feature-only files
    for f in feature_only:
        print(f"[+] {f} only exists with {feature} enabled")
    
    # Generate diffs for matching files
    diff_files = []
    for file1, file2 in matches:
        base_name = os.path.basename(file1)
        output_path = os.path.join(outdir, base_name)
        
        # Run diff command
        try:
            with open(output_path, 'w') as out:
                subprocess.run(
                    ["diff", "-u", file1, file2],
                    stdout=out,
                    stderr=subprocess.PIPE,
                    check=False  # diff returns non-zero when files differ
                )
        except Exception as e:
            print(f"[-] Error diffing {base_name}: {e}")
            continue
    
    # Remove empty diff files
    for covFile in os.listdir(outdir):
        real_file = os.path.join(outdir, covFile)
        if os.path.getsize(real_file) == 0:
            os.remove(real_file)
        else:
            diff_files.append(real_file)
    
    return DiffResult(
        success=True,
        diff_dir=outdir,
        diff_files=diff_files,
        feature_only_files=list(feature_only),
        total_diffs=len(diff_files)
    )
