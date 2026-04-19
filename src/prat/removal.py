"""
Feature code removal module for PRAT.

This module handles the actual removal of feature-specific lines from source
files, as described in Section 7 of the paper. It takes extraction results
and modifies the source tree by removing identified lines.
"""

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from .extraction import ExtractionResult


@dataclass
class RemovalResult:
    """Result of feature code removal."""
    success: bool
    lines_removed: int
    files_modified: int
    files_deleted: int
    backup_dir: Optional[str] = None
    rebuild_success: Optional[bool] = None
    error_message: Optional[str] = None
    per_file_stats: Dict[str, int] = field(default_factory=dict)


def remove_feature_code(
    extraction_result: ExtractionResult,
    project_path: str,
    feature: str,
    feature_only_files: Optional[List[str]] = None,
    backup: bool = True,
    rebuild: bool = True,
    build_command: Optional[List[str]] = None,
) -> RemovalResult:
    """
    Remove feature-specific code from source tree.

    Paper §7: "PRAT removes from the source tree all lines of code
    associated with the features in R."

    Two types of removal:
    1. Line-level: Remove specific lines from shared source files
    2. File-level: Delete entire files that exist only when feature is enabled

    Args:
        extraction_result: Results identifying which lines to remove
        project_path: Path to project root
        feature: Feature name (for logging/backup naming)
        feature_only_files: Files that exist only with this feature (delete entirely)
        backup: If True, create backup of modified files before removal
        rebuild: If True, attempt to rebuild after removal to verify
        build_command: Command to rebuild (auto-detected if None)

    Returns:
        RemovalResult with statistics and rebuild status
    """
    project = Path(project_path)
    total_removed = 0
    files_modified = 0
    files_deleted = 0
    per_file_stats: Dict[str, int] = {}
    backup_dir = None

    print(f"\n[+] Removing {feature} feature code from {project_path}")
    print(f"    Target: {extraction_result.total_removable_lines} lines "
          f"across {len(extraction_result.file_line_counts)} files")

    # Create backup if requested
    if backup:
        backup_dir = str(project / f"_backup_before_remove_{feature}")
        if os.path.exists(backup_dir):
            shutil.rmtree(backup_dir)
        os.makedirs(backup_dir)
        print(f"    Backup dir: {backup_dir}")

    try:
        # --- Line-level removal ---
        for file_name, line_numbers in extraction_result.file_line_numbers.items():
            if not line_numbers:
                continue

            # Find the actual source file in the project
            source_file = _find_source_file(project, file_name)
            if source_file is None:
                print(f"    [!] Source file not found: {file_name}")
                continue

            # Backup original
            if backup and backup_dir:
                rel = source_file.relative_to(project)
                backup_path = Path(backup_dir) / rel
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file, backup_path)

            # Remove lines
            removed = _remove_lines_from_file(source_file, set(line_numbers))
            if removed > 0:
                files_modified += 1
                total_removed += removed
                per_file_stats[file_name] = removed
                print(f"    {file_name}: removed {removed} lines")

        # --- File-level removal ---
        if feature_only_files:
            for file_name in feature_only_files:
                source_file = _find_source_file(project, file_name)
                if source_file is None:
                    continue

                # Backup
                if backup and backup_dir:
                    rel = source_file.relative_to(project)
                    backup_path = Path(backup_dir) / rel
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_file, backup_path)

                # Replace with empty stub so build systems (e.g. CMake) that
                # unconditionally list the file as a source can still find it.
                source_file.write_text(f"/* {file_name}: removed by PRAT (feature-only file) */\n")
                files_deleted += 1
                print(f"    {file_name}: stubbed (feature-only file)")

        print(f"\n    Summary: {total_removed} lines removed, "
              f"{files_modified} files modified, {files_deleted} files deleted")

        # --- Rebuild verification ---
        rebuild_success = None
        if rebuild:
            print("\n[+] Rebuilding to verify removal...")
            rebuild_success = _rebuild_project(project_path, build_command)
            if rebuild_success:
                print("    [+] Rebuild successful — removal is safe")
            else:
                print("    [!] Rebuild FAILED — removal may have broken compilation")

        return RemovalResult(
            success=True,
            lines_removed=total_removed,
            files_modified=files_modified,
            files_deleted=files_deleted,
            backup_dir=backup_dir,
            rebuild_success=rebuild_success,
            per_file_stats=per_file_stats,
        )

    except Exception as e:
        return RemovalResult(
            success=False,
            lines_removed=total_removed,
            files_modified=files_modified,
            files_deleted=files_deleted,
            backup_dir=backup_dir,
            error_message=f"Feature removal failed: {e}",
            per_file_stats=per_file_stats,
        )


def restore_from_backup(backup_dir: str, project_path: str) -> bool:
    """
    Restore source files from a backup created during removal.

    Args:
        backup_dir: Path to backup directory
        project_path: Path to project root

    Returns:
        True if restoration successful
    """
    backup = Path(backup_dir)
    project = Path(project_path)

    if not backup.exists():
        print(f"[!] Backup directory not found: {backup_dir}")
        return False

    try:
        restored = 0
        for backup_file in backup.rglob("*"):
            if not backup_file.is_file():
                continue

            rel = backup_file.relative_to(backup)
            target = project / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_file, target)
            restored += 1

        print(f"[+] Restored {restored} files from backup")
        return True

    except Exception as e:
        print(f"[!] Restoration failed: {e}")
        return False


def _find_source_file(project: Path, file_name: str) -> Optional[Path]:
    """
    Find a source file in the project tree by name.

    Handles cases where the file_name from coverage might be just
    the basename (e.g., "net.c") and needs to be located in the tree.
    """
    # Try exact match first
    exact = project / file_name
    if exact.exists():
        return exact

    # Search src/ and lib/ directories
    for search_dir in ["src", "lib", "."]:
        candidate = project / search_dir / file_name
        if candidate.exists():
            return candidate

    # Recursive search as last resort
    for match in project.rglob(file_name):
        if match.is_file() and "__pycache__" not in str(match):
            return match

    return None


def _remove_lines_from_file(file_path: Path, line_numbers: Set[int]) -> int:
    """
    Remove specific lines from a source file.

    Lines are replaced with empty lines to preserve line numbering
    (important for debugging and subsequent gcov runs).

    Args:
        file_path: Path to source file
        line_numbers: Set of 1-indexed line numbers to remove

    Returns:
        Number of lines actually removed
    """
    try:
        with open(file_path, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        removed = 0
        for i, line in enumerate(lines):
            line_num = i + 1  # 1-indexed
            if line_num in line_numbers:
                # Replace with empty line to preserve numbering
                lines[i] = "\n"
                removed += 1

        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        return removed

    except Exception as e:
        print(f"    [!] Error modifying {file_path}: {e}")
        return 0


def _rebuild_project(
    project_path: str,
    build_command: Optional[List[str]] = None,
) -> bool:
    """
    Attempt to rebuild the project after code removal.

    Args:
        project_path: Path to project root
        build_command: Build command (auto-detected if None)

    Returns:
        True if rebuild succeeded
    """
    if build_command is None:
        # Auto-detect build command
        project = Path(project_path)
        if (project / "Cargo.toml").exists():
            build_command = ["cargo", "build"]
        elif (project / "CMakeLists.txt").exists():
            build_command = ["make", "-C", "build", "-j"]
        elif (project / "Makefile").exists():
            build_command = ["make", "-j"]
        else:
            print("    [!] Cannot auto-detect build command")
            return False

    try:
        proc = subprocess.run(
            build_command,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=600,
        )
        return proc.returncode == 0

    except subprocess.TimeoutExpired:
        print("    [!] Rebuild timed out")
        return False
    except Exception as e:
        print(f"    [!] Rebuild error: {e}")
        return False
