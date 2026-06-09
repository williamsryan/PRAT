"""Tests for prat.removal module."""

from pathlib import Path

import pytest

from prat.extraction import ExtractionResult
from prat.removal import (
    _find_source_file,
    _remove_lines_from_file,
    remove_feature_code,
    restore_from_backup,
)


@pytest.fixture
def sample_project(tmp_path):
    """Create a minimal project with source files."""
    src = tmp_path / "src"
    src.mkdir()

    (src / "net.c").write_text(
        "#include <stdio.h>\n"
        "void net_init() { }\n"
        "void tls_init() { }\n"
        "void tls_connect() { }\n"
        "int main() { net_init(); return 0; }\n"
    )
    (src / "tls_mosq.c").write_text(
        "#include <openssl/ssl.h>\n"
        "void tls_setup() { }\n"
        "void tls_verify() { }\n"
    )
    (tmp_path / "Makefile").write_text("all:\n\techo done\n")

    return tmp_path


@pytest.fixture
def sample_extraction():
    return ExtractionResult(
        success=True,
        file_line_counts={"net.c": 2, "tls_mosq.c": 2},
        total_removable_lines=4,
        file_line_numbers={"net.c": [3, 4], "tls_mosq.c": [2, 3]},
        file_line_content={
            "net.c": ["void tls_init() { }", "void tls_connect() { }"],
            "tls_mosq.c": ["void tls_setup() { }", "void tls_verify() { }"],
        },
    )


class TestFindSourceFile:
    def test_finds_in_src(self, sample_project):
        result = _find_source_file(sample_project, "net.c")
        assert result is not None
        assert result.name == "net.c"

    def test_finds_nonexistent_returns_none(self, sample_project):
        result = _find_source_file(sample_project, "nonexistent.c")
        assert result is None


class TestRemoveLines:
    def test_removes_specified_lines(self, sample_project):
        src_file = sample_project / "src" / "net.c"
        original = src_file.read_text().split("\n")
        original_count = len(original)

        removed = _remove_lines_from_file(src_file, {3, 4})

        assert removed == 2
        modified = src_file.read_text().split("\n")
        # Line count preserved (empty lines replace removed ones)
        assert len(modified) == original_count
        # Lines 3 and 4 are now empty
        assert modified[2] == ""
        assert modified[3] == ""
        # Other lines untouched
        assert "stdio" in modified[0]

    def test_no_removal_on_empty_set(self, sample_project):
        src_file = sample_project / "src" / "net.c"
        original = src_file.read_text()

        removed = _remove_lines_from_file(src_file, set())

        assert removed == 0
        assert src_file.read_text() == original


class TestRemoveFeatureCode:
    def test_removes_lines_and_creates_backup(self, sample_project, sample_extraction):
        result = remove_feature_code(
            sample_extraction,
            str(sample_project),
            "TLS",
            backup=True,
            rebuild=False,
        )

        assert result.success is True
        assert result.lines_removed == 4
        assert result.files_modified == 2
        assert result.backup_dir is not None
        assert Path(result.backup_dir).exists()

    def test_no_backup_when_disabled(self, sample_project, sample_extraction):
        result = remove_feature_code(
            sample_extraction,
            str(sample_project),
            "TLS",
            backup=False,
            rebuild=False,
        )

        assert result.success is True
        assert result.backup_dir is None

    def test_file_level_removal(self, sample_project, sample_extraction):
        result = remove_feature_code(
            sample_extraction,
            str(sample_project),
            "TLS",
            feature_only_files=["tls_mosq.c"],
            backup=True,
            rebuild=False,
        )

        assert result.files_deleted == 1
        stub = (sample_project / "src" / "tls_mosq.c")
        assert stub.exists()
        assert "removed by PRAT" in stub.read_text()

    def test_per_file_stats(self, sample_project, sample_extraction):
        result = remove_feature_code(
            sample_extraction,
            str(sample_project),
            "TLS",
            rebuild=False,
        )

        assert "net.c" in result.per_file_stats
        assert result.per_file_stats["net.c"] == 2


class TestRestoreFromBackup:
    def test_restores_files(self, sample_project, sample_extraction):
        # Remove first
        result = remove_feature_code(
            sample_extraction,
            str(sample_project),
            "TLS",
            backup=True,
            rebuild=False,
        )

        # Verify lines were removed
        net_c = (sample_project / "src" / "net.c").read_text()
        assert "tls_init" not in net_c

        # Restore
        restored = restore_from_backup(result.backup_dir, str(sample_project))
        assert restored is True

        # Verify restoration
        net_c_restored = (sample_project / "src" / "net.c").read_text()
        assert "tls_init" in net_c_restored
