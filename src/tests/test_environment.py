"""Tests for prat.environment module."""

from unittest.mock import patch

from prat.environment import EnvironmentResult, is_tool_available, verify_dependencies


class TestVerifyDependencies:
    """Tests for verify_dependencies()."""

    @patch("prat.environment.shutil.which")
    def test_all_tools_available(self, mock_which):
        """When all tools are on PATH, result should be successful."""
        mock_which.return_value = "/usr/bin/fake"

        result = verify_dependencies()

        assert isinstance(result, EnvironmentResult)
        assert result.success is True
        assert len(result.missing_tools) == 0

    @patch("prat.environment.shutil.which")
    def test_missing_required_tool(self, mock_which):
        """When a required tool is missing, it appears in missing_tools."""

        def which_side_effect(cmd):
            if cmd == "gcc":
                return None
            return "/usr/bin/fake"

        mock_which.side_effect = which_side_effect

        result = verify_dependencies()

        assert result.success is False
        assert "gcc" in result.missing_tools
        assert result.error_message is not None

    @patch("prat.environment.shutil.which")
    def test_optional_tools_dont_cause_failure(self, mock_which):
        """pygmentize and xdot are optional — missing them shouldn't fail."""

        def which_side_effect(cmd):
            if cmd in ("pygmentize", "xdot"):
                return None
            return "/usr/bin/fake"

        mock_which.side_effect = which_side_effect

        result = verify_dependencies()

        # Should still succeed — pygmentize/xdot are optional
        assert result.success is True
        assert "pygmentize" not in result.missing_tools
        assert "xdot" not in result.missing_tools

    @patch("prat.environment.shutil.which")
    def test_available_tools_dict_populated(self, mock_which):
        """available_tools dict should have entries for every checked tool."""
        mock_which.return_value = "/usr/bin/fake"

        result = verify_dependencies()

        assert "gcc" in result.available_tools
        assert "make" in result.available_tools
        assert "python3" in result.available_tools
        assert result.available_tools["gcc"] is True


class TestIsToolAvailable:
    """Tests for is_tool_available()."""

    @patch("prat.environment.shutil.which")
    def test_tool_found(self, mock_which):
        mock_which.return_value = "/usr/bin/gcc"
        assert is_tool_available("gcc") is True

    @patch("prat.environment.shutil.which")
    def test_tool_not_found(self, mock_which):
        mock_which.return_value = None
        assert is_tool_available("nonexistent") is False
