"""Tests for prat.adapters module."""

from unittest.mock import patch

import pytest

from prat.adapters import get_adapter
from prat.adapters.cmake import CMakeAdapter
from prat.adapters.ffmpeg import FFmpegAdapter
from prat.adapters.mosquitto import MosquittoAdapter
from prat.adapters.rust import RustAdapter
from prat.compilation import BuildSystem


class TestGetAdapter:
    """Tests for the adapter factory."""

    def test_returns_none_for_empty_dir(self, tmp_path):
        adapter = get_adapter(str(tmp_path))
        assert adapter is None

    def test_detects_mosquitto(self, tmp_path):
        (tmp_path / "Makefile").touch()
        (tmp_path / "config.mk").touch()
        (tmp_path / "src").mkdir()

        adapter = get_adapter(str(tmp_path))

        assert adapter is not None
        assert isinstance(adapter, MosquittoAdapter)

    def test_detects_ffmpeg(self, tmp_path):
        (tmp_path / "configure").touch()
        (tmp_path / "libavcodec").mkdir()

        adapter = get_adapter(str(tmp_path))

        assert adapter is not None
        assert isinstance(adapter, FFmpegAdapter)

    def test_detects_rust(self, tmp_path):
        (tmp_path / "Cargo.toml").touch()
        (tmp_path / "src").mkdir()

        adapter = get_adapter(str(tmp_path))

        assert adapter is not None
        assert isinstance(adapter, RustAdapter)

    def test_detects_cmake(self, tmp_path):
        (tmp_path / "CMakeLists.txt").touch()

        adapter = get_adapter(str(tmp_path))

        assert adapter is not None
        assert isinstance(adapter, CMakeAdapter)


class TestMosquittoAdapter:
    """Tests for MosquittoAdapter."""

    @pytest.fixture
    def adapter(self, tmp_path):
        (tmp_path / "Makefile").touch()
        (tmp_path / "config.mk").touch()
        (tmp_path / "src").mkdir()
        return MosquittoAdapter(str(tmp_path))

    def test_source_directories(self, adapter):
        assert "src" in adapter.source_directories
        assert "lib" in adapter.source_directories

    def test_validate_project(self, adapter):
        assert adapter.validate_project() is True

    # --- Linux (Make) path ---

    def test_build_system_linux(self, adapter):
        with patch("prat.adapters.mosquitto._is_macos", return_value=False):
            assert adapter.build_system == BuildSystem.MAKE

    def test_coverage_tool_linux(self, adapter):
        with patch("prat.adapters.mosquitto._is_macos", return_value=False):
            assert adapter.coverage_tool == "gcov"

    def test_feature_flag_enabled_linux(self, adapter):
        with patch("prat.adapters.mosquitto._is_macos", return_value=False):
            assert adapter.format_feature_flag("TLS", True) == "WITH_TLS=yes"

    def test_feature_flag_disabled_linux(self, adapter):
        with patch("prat.adapters.mosquitto._is_macos", return_value=False):
            assert adapter.format_feature_flag("TLS", False) == "WITH_TLS=no"

    def test_compile_command_linux(self, adapter):
        with patch("prat.adapters.mosquitto._is_macos", return_value=False):
            cmd = adapter.get_compile_command("TLS", True)
            assert "make" in cmd
            assert "WITH_COVERAGE=yes" in cmd
            assert "WITH_TLS=yes" in cmd

    def test_clean_command_linux(self, adapter):
        with patch("prat.adapters.mosquitto._is_macos", return_value=False):
            assert adapter.get_clean_command() == ["make", "clean"]

    # --- macOS (CMake) path ---

    def test_build_system_macos(self, adapter):
        with patch("prat.adapters.mosquitto._is_macos", return_value=True):
            assert adapter.build_system == BuildSystem.CMAKE

    def test_coverage_tool_macos(self, adapter):
        with patch("prat.adapters.mosquitto._is_macos", return_value=True):
            assert adapter.coverage_tool == "gcov"

    def test_feature_flag_enabled_macos(self, adapter):
        with patch("prat.adapters.mosquitto._is_macos", return_value=True):
            assert adapter.format_feature_flag("TLS", True) == "-DWITH_TLS=ON"

    def test_feature_flag_disabled_macos(self, adapter):
        with patch("prat.adapters.mosquitto._is_macos", return_value=True):
            assert adapter.format_feature_flag("TLS", False) == "-DWITH_TLS=OFF"

    def test_compile_command_macos(self, adapter):
        with patch("prat.adapters.mosquitto._is_macos", return_value=True):
            cmd = adapter.get_compile_command("TLS", True)
            assert cmd[:4] == ["cmake", "-B", "build", "-S"]
            assert "-DWITH_TLS=ON" in cmd
            assert "-DCMAKE_C_FLAGS=--coverage" in cmd

    def test_build_commands_macos(self, adapter):
        with patch("prat.adapters.mosquitto._is_macos", return_value=True):
            cmds = adapter.get_build_commands("TLS", True)
            assert len(cmds) == 2
            assert cmds[0][0] == "cmake"
            assert cmds[1] == ["make", "-C", "build", "-j"]

    def test_clean_command_macos(self, adapter):
        with patch("prat.adapters.mosquitto._is_macos", return_value=True):
            cmd = adapter.get_clean_command()
            assert cmd[0] == "bash"
            assert "--target clean" in cmd[2]
            assert "*.gcda" in cmd[2]


class TestFFmpegAdapter:
    """Tests for FFmpegAdapter."""

    @pytest.fixture
    def adapter(self, tmp_path):
        (tmp_path / "configure").touch()
        (tmp_path / "libavcodec").mkdir()
        return FFmpegAdapter(str(tmp_path))

    def test_build_system(self, adapter):
        assert adapter.build_system == BuildSystem.AUTOTOOLS

    def test_coverage_tool(self, adapter):
        assert adapter.coverage_tool == "gcov"

    def test_feature_flag_disabled(self, adapter):
        flag = adapter.format_feature_flag("x264", False)
        assert flag == "--disable-x264"

    def test_feature_flag_enabled(self, adapter):
        flag = adapter.format_feature_flag("x264", True)
        assert flag == "--enable-x264"

    def test_compile_command_disabled(self, adapter):
        cmd = adapter.get_compile_command("x264", False)
        assert "--toolchain=gcov" in cmd
        # "x264" maps to FFmpeg's real option name "libx264"; a bare
        # "--disable-x264" is not a valid configure option.
        assert "--disable-libx264" in cmd

    def test_compile_command_enabled(self, adapter):
        cmd = adapter.get_compile_command("x264", True)
        assert "--enable-libx264" in cmd
        assert "--enable-gpl" in cmd


class TestRustAdapter:
    """Tests for RustAdapter."""

    @pytest.fixture
    def adapter(self, tmp_path):
        (tmp_path / "Cargo.toml").touch()
        (tmp_path / "src").mkdir()
        return RustAdapter(str(tmp_path))

    def test_build_system(self, adapter):
        assert adapter.build_system == BuildSystem.CARGO

    def test_compile_command_enabled(self, adapter):
        cmd = adapter.get_compile_command("tls", True)
        assert "cargo" in cmd
        assert "--features" in cmd

    def test_compile_command_disabled(self, adapter):
        # DISABLED keeps default features (feature simply omitted); we must NOT
        # use --no-default-features (it would drop required defaults like a TLS
        # backend and break the build).
        cmd = adapter.get_compile_command("tls", False)
        assert "--features" not in cmd
        assert "--no-default-features" not in cmd
        assert cmd[:2] == ["cargo", "build"]

    def test_llvm_cov_command(self, adapter):
        enabled = adapter.get_llvm_cov_command("qlog", True, "/tmp/c.lcov")
        assert enabled[:3] == ["cargo", "llvm-cov", "--lib"]
        assert "--features" in enabled and "qlog" in enabled
        assert "--lcov" in enabled
        disabled = adapter.get_llvm_cov_command("qlog", False, "/tmp/c.lcov")
        assert "--features" not in disabled

    def test_coverage_environment_empty(self, adapter):
        # cargo-llvm-cov manages instrumentation itself.
        assert adapter.get_coverage_environment() == {}


class TestCMakeAdapter:
    """Tests for CMakeAdapter."""

    @pytest.fixture
    def adapter(self, tmp_path):
        (tmp_path / "CMakeLists.txt").touch()
        return CMakeAdapter(str(tmp_path))

    def test_build_system(self, adapter):
        assert adapter.build_system == BuildSystem.CMAKE

    def test_feature_flag(self, adapter):
        flag = adapter.format_feature_flag("TLS", True)
        assert flag == "-DCONFIG_TLS=1"

        flag = adapter.format_feature_flag("TLS", False)
        assert flag == "-DCONFIG_TLS=0"

    def test_compile_command_has_coverage_flags(self, adapter):
        cmd = adapter.get_compile_command("TLS", True)
        assert any("--coverage" in arg for arg in cmd)
