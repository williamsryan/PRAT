"""
Feature extraction module for PRAT.

This module handles parsing diff files to identify and count feature-specific
lines of code that can be removed.
"""

import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class ExtractionResult:
    """Result of feature extraction operation."""
    success: bool
    file_line_counts: Dict[str, int]  # filename -> removable line count
    total_removable_lines: int
    file_line_numbers: Dict[str, List[int]]  # filename -> list of line numbers
    file_line_content: Dict[str, List[str]]  # filename -> list of line content
    error_message: Optional[str] = None


def count_removable_lines(diff_file: str) -> int:
    """
    Count lines marked with ##### in a diff file.
    
    Args:
        diff_file: Path to diff file
    
    Returns:
        Count of never-executed lines (marked with #####)
    """
    if not os.path.exists(diff_file):
        return 0
    
    count = 0
    try:
        with open(diff_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                # Look for ##### markers (never-executed code)
                # Exclude /*EOF*/ markers
                if '#####' in line and '/*EOF*/' not in line:
                    count += 1
    except Exception as e:
        print(f"[-] Error reading {diff_file}: {e}")
        return 0
    
    return count


def extract_features(diff_dir: str) -> ExtractionResult:
    """
    Parse diff files and extract feature-specific code.
    
    Args:
        diff_dir: Directory containing diff files
    
    Returns:
        ExtractionResult with line counts and file mappings
    """
    print(f"[+] Extract features for removal from: {diff_dir}")
    
    if not os.path.exists(diff_dir):
        return ExtractionResult(
            success=False,
            file_line_counts={},
            total_removable_lines=0,
            file_line_numbers={},
            file_line_content={},
            error_message=f"Diff directory does not exist: {diff_dir}"
        )
    
    # Get all diff files
    diff_files = [f for f in os.listdir(diff_dir) 
                  if os.path.isfile(os.path.join(diff_dir, f))]
    
    if not diff_files:
        return ExtractionResult(
            success=False,
            file_line_counts={},
            total_removable_lines=0,
            file_line_numbers={},
            file_line_content={},
            error_message=f"No diff files found in {diff_dir}"
        )
    
    # Data structures to store results
    file_line_counts = {}
    file_line_numbers = {}
    file_line_content = {}
    total_lines = 0
    
    # Process each diff file
    for diff_file in diff_files:
        file_path = os.path.join(diff_dir, diff_file)
        
        # Extract base filename (remove .gcov extension)
        # Format: filename.c.gcov -> filename.c
        file_name = diff_file
        if file_name.endswith('.gcov'):
            file_name = file_name[:-5]  # Remove .gcov
        
        # Parse the diff file
        line_numbers = []
        line_contents = []
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    # Look for ##### markers (never-executed code)
                    # Exclude /*EOF*/ markers
                    if '#####' in line and '/*EOF*/' not in line:
                        # Extract line number: format is "    #####:  123:code"
                        match = re.search(r'(\d+):', line)
                        if match:
                            line_num = int(match.group(1))
                            line_numbers.append(line_num)
                        
                        # Extract source code content
                        # Format: "    #####:  123:source code here"
                        match = re.search(r'\d+:(.*)', line)
                        if match:
                            source = match.group(1)
                            # Escape quotes for later use
                            source = source.replace('"', '\\"')
                            line_contents.append(source)
        except Exception as e:
            print(f"[-] Error parsing {diff_file}: {e}")
            continue
        
        # Store results if we found removable lines
        if line_numbers:
            count = len(line_numbers)
            file_line_counts[file_name] = count
            file_line_numbers[file_name] = line_numbers
            file_line_content[file_name] = line_contents
            total_lines += count
            
            print(f"\n------------------")
            print(f"Lines to remove from {file_name}")
            print(f"------------------")
            print(f"Count: {count}")
    
    print(f"\n------------------")
    print(f"Total lines to remove: {total_lines}")
    print(f"------------------")
    
    # Print summary
    for file_name, line_nums in file_line_numbers.items():
        print(f"\t{file_name}: {line_nums}")
    
    return ExtractionResult(
        success=True,
        file_line_counts=file_line_counts,
        total_removable_lines=total_lines,
        file_line_numbers=file_line_numbers,
        file_line_content=file_line_content,
        error_message=None
    )
