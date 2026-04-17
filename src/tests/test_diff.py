"""Tests for prat.diff module."""

import os
import pytest
from unittest.mock import patch, MagicMock

from prat.diff import match_coverage_files, diff_coverage_files, DiffResult


class TestMatchCoverageFiles:
    """Tests for match_coverage_files()."""

    def test_matching_files(self, tmp_path):
        dir1 = tmp_path / "enabled"
        dir2 = tmp_path / "disabled"
        dir1.mkdir()
        dir2.mkdir()

        (dir1 / "net.c.gcov").write_text("content1")
        (dir1 / "tls.c.gcov").write_text("content2")
        (dir2 / "net.c.gcov").write_text("content3")
        (dir2 / "tls.c.gcov").write_text("content4")

        matches = match_coverage_files(str(dir1), str(dir2))

        assert len(matches) == 2
        basenames = {os.path.basename(m[0]) for m in matches}
        assert basenames == {"net.c.gcov", "tls.c.gcov"}

    def test_partial_overlap(self, tmp_path):
        dir1 = tmp_path / "enabled"
        dir2 = tmp_path / "disabled"
        dir1.mkdir()
        dir2.mkdir()

        (dir1 / "net.c.gcov").write_text("content1")
        (dir1 / "tls.c.gcov").write_text("content2")  # only in enabled
        (dir2 / "net.c.gcov").write_text("content3")

        matches = match_coverage_files(str(dir1), str(dir2))

        assert len(matches) == 1
        assert "net.c" in matches[0][0]

    def test_nonexistent_directory(self, tmp_path):
        matches = match_coverage_files(str(tmp_path / "nope"), str(tmp_path))
        assert matches == []

    def test_empty_directories(self, tmp_path):
        dir1 = tmp_path / "a"
        dir2 = tmp_path / "b"
        dir1.mkdir()
        dir2.mkdir()

        matches = match_coverage_files(str(dir1), str(dir2))
        assert matches == []


class TestDiffCoverageFiles:
    """Tests for diff_coverage_files()."""

    def test_nonexistent_enabled_dir(self, tmp_path):
        result = diff_coverage_files(
            str(tmp_path / "nope"), str(tmp_path), "TLS"
        )
        assert result.success is False
        assert "does not exist" in result.error_message

    @patch("prat.diff.subprocess.run")
    def test_successful_diff(self, mock_run, tmp_path):
        enabled = tmp_path / "enabled"
        disabled = tmp_path / "disabled"
        enabled.mkdir()
        disabled.mkdir()

        # Create files that differ
        (enabled / "net.c.gcov").write_text("line1\n#####: 10: code\n")
        (disabled / "net.c.gcov").write_text("line1\n    1: 10: code\n")

        # Mock diff to write something
        def diff_side_effect(cmd, **kwargs):
            if "stdout" in kwargs and kwargs["stdout"]:
                kwargs["stdout"].write("--- a\n+++ b\n@@ diff @@\n")
            return MagicMock(returncode=1)  # diff returns 1 when files differ

        mock_run.side_effect = diff_side_effect

        result = diff_coverage_files(
            str(enabled), str(disabled), "TLS", output_dir=str(tmp_path)
        )

        assert result.success is True
        assert result.total_diffs >= 0

    @patch("prat.diff.subprocess.run")
    def test_feature_only_files_detected(self, mock_run, tmp_path):
        enabled = tmp_path / "enabled"
        disabled = tmp_path / "disabled"
        enabled.mkdir()
        disabled.mkdir()

        # tls.c only in enabled
        (enabled / "net.c.gcov").write_text("content")
        (enabled / "tls.c.gcov").write_text("content")
        (disabled / "net.c.gcov").write_text("content")

        mock_run.return_value = MagicMock(returncode=0)

        result = diff_coverage_files(
            str(enabled), str(disabled), "TLS", output_dir=str(tmp_path)
        )

        assert "tls.c" in result.feature_only_files
