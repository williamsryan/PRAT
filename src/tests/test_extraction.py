"""Tests for prat.extraction module."""


from prat.extraction import ExtractionResult, count_removable_lines, extract_features


class TestCountRemovableLines:
    """Tests for count_removable_lines()."""

    def test_counts_hash_lines(self, tmp_path):
        diff_file = tmp_path / "net.c.gcov"
        diff_file.write_text(
            "    1:   1: #include <stdio.h>\n"
            "#####:   2: tls_init();\n"
            "#####:   3: tls_connect();\n"
            "    1:   4: return 0;\n"
        )

        count = count_removable_lines(str(diff_file))
        assert count == 2

    def test_excludes_eof_markers(self, tmp_path):
        diff_file = tmp_path / "net.c.gcov"
        diff_file.write_text(
            "#####:   1: tls_init();\n"
            "#####:   2: /*EOF*/\n"
        )

        count = count_removable_lines(str(diff_file))
        # Second line has /*EOF*/ so should be excluded
        assert count == 1

    def test_nonexistent_file(self):
        count = count_removable_lines("/nonexistent/path")
        assert count == 0

    def test_empty_file(self, tmp_path):
        diff_file = tmp_path / "empty.gcov"
        diff_file.write_text("")

        count = count_removable_lines(str(diff_file))
        assert count == 0


class TestExtractFeatures:
    """Tests for extract_features()."""

    def test_nonexistent_dir(self):
        result = extract_features("/nonexistent")
        assert result.success is False
        assert "does not exist" in result.error_message

    def test_empty_dir(self, tmp_path):
        result = extract_features(str(tmp_path))
        assert result.success is False
        assert "No diff files" in result.error_message

    def test_extracts_removable_lines(self, tmp_path):
        # Create a diff file with ##### markers
        diff_file = tmp_path / "net.c.gcov"
        diff_file.write_text(
            "+#####:  10: ssl_ctx = SSL_CTX_new();\n"
            "+#####:  11: SSL_CTX_set_options(ctx);\n"
            " -    1:  12: return 0;\n"
        )

        result = extract_features(str(tmp_path), feature="TLS")

        assert result.success is True
        assert result.total_removable_lines == 2
        assert isinstance(result, ExtractionResult)

    def test_multiple_files(self, tmp_path):
        (tmp_path / "net.c.gcov").write_text(
            "+#####:  10: ssl_init();\n"
        )
        (tmp_path / "tls.c.gcov").write_text(
            "+#####:  20: tls_handshake();\n"
            "+#####:  21: tls_verify();\n"
        )

        result = extract_features(str(tmp_path), feature="TLS")

        assert result.success is True
        assert result.total_removable_lines == 3
        assert len(result.file_line_counts) == 2

    def test_gcov_extension_stripped(self, tmp_path):
        """File names should have .gcov removed."""
        (tmp_path / "net.c.gcov").write_text(
            "+#####:  10: code;\n"
        )

        result = extract_features(str(tmp_path))

        assert "net.c" in result.file_line_counts

    def test_result_fields(self, tmp_path):
        (tmp_path / "test.c.gcov").write_text(
            "+#####:  5: int x = 1;\n"
        )

        result = extract_features(str(tmp_path), feature="TLS", output_dir=str(tmp_path))

        assert result.html_report_path is None  # Not set by extract_features itself
        assert result.dot_graph_path is None
        assert result.error_message is None
        assert 5 in result.file_line_numbers.get("test.c", [])
