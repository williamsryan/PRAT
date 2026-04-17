"""Tests for prat.adapters module."""

import pytest
from pathlib import Path

from prat.adapters import get_adapter
from prat.adapters.base import ProjectAdapter
from prat.adapters.mosquitto import MosquittoAdapter
from prat.adapters.ffmpeg import FFmpegAdapter
from prat.adapters.cmake import CMakeAdapter
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

    def test_build_system(self, adapter):
        assert adapter.build_system == BuildSystem.MAKE

    def test_coverage_tool(self, adapter):
        assert adapter.coverage_tool == "llvm-cov-9"

    def test_source_directories(self, adapter):
        assert "src" in adapter.source_directories
        assert "lib" in adapter.source_directories

    def test_feature_flag_enabled(self, adapter):
        flag = adapter.format_feature_flag("TLS", True)
        assert flag == "WITH_TLS=yes"

    def test_feature_flag_disabled(self, adapter):
        flag = adapter.format_feature_flag("TLS", False)
        assert flag == "WITH_TLS=no"

    def test_compile_command(self, adapter):
        cmd = adapter.get_compile_command("TLS", True)
        assert "make" in cmd
        assert "WITH_COVERAGE=yes" in cmd
        assert "WITH_TLS=yes" in cmd

    def test_clean_command(self, adapter):
        cmd = adapter.get_clean_command()
        assert cmd == ["make", "clean"]

    def test_validate_project(self, adapter):
        assert adapter.validate_project() is True


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
        assert "--disable-x264" in cmd


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
        cmd = adapter.get_compile_command("tls", False)
        assert "--no-default-features" in cmd

    def test_coverage_environment(self, adapter):
        env = adapter.get_coverage_environment()
        assert "RUSTFLAGS" in env
        assert "CARGO_INCREMENTAL" in env


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
