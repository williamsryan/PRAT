"""Tests for prat.adapters module."""

from unittest.mock import patch

import pytest

from prat.adapters import get_adapter
from prat.adapters.aom import AomAdapter
from prat.adapters.cmake import CMakeAdapter
from prat.adapters.ffmpeg import FFmpegAdapter
from prat.adapters.mosquitto import MosquittoAdapter
from prat.adapters.opendds import OpenDDSAdapter
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

    # --- The fixed test plan T ---

    def test_linux_test_plan_is_the_unit_tests(self, adapter):
        with patch("prat.adapters.mosquitto._is_macos", return_value=False):
            assert adapter.get_test_plan(["TLS", "BRIDGE"]) == [
                ["make", "utest", "-j", "WITH_COVERAGE=yes"]
            ]

    def test_macos_test_plan_has_a_plain_session_that_runs_on_every_build(
        self, adapter, tmp_path
    ):
        """Against B_TLS the TLS sessions cannot run; the plain session must
        still contribute coverage, or L_TLS would be empty and D_TLS = L_all."""
        with (
            patch("prat.adapters.mosquitto._is_macos", return_value=True),
            patch.object(
                MosquittoAdapter, "_ensure_test_certificates",
                return_value=tmp_path / "build" / "prat_ssl",
            ),
        ):
            plan = adapter.get_test_plan(["TLS", "BRIDGE"])
            again = adapter.get_test_plan(["BRIDGE"])

        assert len(plan) == 7
        plain = plan[0][2]
        assert "-p 11883" in plain and "cafile" not in plain
        assert "mosquitto_sub" in plain and "mosquitto_pub" in plain
        for tls_session in plan[1:6]:
            assert "-p 18883" in tls_session[2]
        # The plan does not depend on which feature is being analysed.
        assert again == plan
        # Both listener configs carry a string-valued option so the generic
        # string parser is shared code, not D_TLS.
        plain_conf = (tmp_path / "build" / "prat_plain.conf").read_text().splitlines()
        assert plain_conf[0] == "allow_anonymous true"
        assert plain_conf[1].startswith("pid_file ")
        assert plain_conf[2] == "listener 11883"
        tls_conf = (tmp_path / "build" / "prat_tls.conf").read_text()
        assert "cafile" in tls_conf and "pid_file" in tls_conf

    def test_macos_test_plan_exercises_tls_options_and_error_paths(
        self, adapter, tmp_path
    ):
        with (
            patch("prat.adapters.mosquitto._is_macos", return_value=True),
            patch.object(
                MosquittoAdapter, "_ensure_test_certificates",
                return_value=tmp_path / "build" / "prat_ssl",
            ),
        ):
            plan = adapter.get_test_plan(["TLS"])
        scripts = [command[2] for command in plan]

        assert "--tls-version tlsv1.2 --ciphers HIGH --insecure" in scripts[2]
        assert "-h 127.0.0.1" in scripts[2]
        assert "--cert " in scripts[3] and "--key " in scripts[3]
        assert "--capath " in scripts[4]
        # Expected failures are asserted, not merely tolerated.
        assert scripts[5].count("then exit 1; fi") == 3
        assert "other_ca.crt" in scripts[5] and "missing.crt" in scripts[5]
        assert "does-not-exist.crt" in (
            tmp_path / "build" / "prat_tls_bad_certfile.conf").read_text()
        assert "exit 1" in scripts[6]

        options_conf = (tmp_path / "build" / "prat_tls_options.conf").read_text()
        assert "tls_version tlsv1.2" in options_conf and "ciphers HIGH:!aNULL" in options_conf
        mutual_conf = (tmp_path / "build" / "prat_tls_mutual.conf").read_text()
        assert "require_certificate true" in mutual_conf
        assert "use_subject_as_username true" in mutual_conf

    def test_macos_session_always_stops_its_broker(self, adapter, tmp_path):
        """A failing client must not leave the broker holding the port and the
        output pipes open until the coverage timeout."""
        with (
            patch("prat.adapters.mosquitto._is_macos", return_value=True),
            patch.object(
                MosquittoAdapter, "_ensure_test_certificates",
                return_value=tmp_path / "build" / "prat_ssl",
            ),
        ):
            scripts = [command[2] for command in adapter.get_test_plan(["TLS"])]

        for script in scripts[:6]:
            assert "trap 'kill -TERM $BROKER_PID" in script
            assert ">/dev/null 2>&1 &" in script
            assert script.startswith("set -e\n")
        # The must-not-start probe has no trap because the broker is expected
        # to have exited; if it is alive it is stopped before failing.
        assert "kill -TERM $BROKER_PID; wait $BROKER_PID" in scripts[6]

    def test_macos_generates_its_own_certificates(self, adapter):
        """Mosquitto's shipped test certificates have expired; PRAT generates a
        CA, a localhost server certificate, a client certificate, an unrelated
        CA and a capath layout under build/ instead."""
        import shutil

        import pytest

        if not shutil.which("openssl"):
            pytest.skip("openssl is not installed")
        with patch("prat.adapters.mosquitto._is_macos", return_value=True):
            ssl_dir = adapter._ensure_test_certificates()

        for name in ("ca.crt", "server.crt", "server.key", "client.crt", "client.key",
                     "other_ca.crt", "ready"):
            assert (ssl_dir / name).exists(), name
        hashed = list((ssl_dir / "capath").glob("*.0"))
        assert len(hashed) == 1
        assert hashed[0].read_bytes() == (ssl_dir / "ca.crt").read_bytes()
        assert ssl_dir == adapter.project_path.resolve() / "build" / "prat_ssl"
        # Idempotent: a second call reuses the files.
        before = (ssl_dir / "server.crt").read_bytes()
        assert adapter._ensure_test_certificates() == ssl_dir
        assert (ssl_dir / "server.crt").read_bytes() == before

    def test_partial_certificate_directory_is_regenerated(self, adapter):
        """A directory from an older PRAT (server.crt but no client.crt or
        marker) is regenerated instead of trusted."""
        import shutil

        import pytest

        if not shutil.which("openssl"):
            pytest.skip("openssl is not installed")
        ssl_dir = adapter.project_path.resolve() / "build" / "prat_ssl"
        ssl_dir.mkdir(parents=True)
        (ssl_dir / "server.crt").write_text("stale")
        with patch("prat.adapters.mosquitto._is_macos", return_value=True):
            adapter._ensure_test_certificates()
        assert (ssl_dir / "server.crt").read_text() != "stale"
        assert (ssl_dir / "client.crt").exists()


class TestAomAdapter:
    """Tests for AomAdapter's fixed test plan."""

    @pytest.fixture
    def adapter(self, tmp_path):
        (tmp_path / "CMakeLists.txt").touch()
        (tmp_path / "av1").mkdir()
        return AomAdapter(str(tmp_path))

    def test_test_plan_is_fixed_and_exercises_encoder_and_decoder(self, adapter):
        plan = adapter.get_test_plan(["CONFIG_AV1_ENCODER", "CONFIG_AV1_DECODER"])

        assert plan == adapter.get_test_plan(["CONFIG_AV1_DECODER"])
        assert plan[0][0] == "sh"
        assert sum("aomenc" in cmd[0] for cmd in plan) == 2
        assert sum("aomdec" in cmd[0] for cmd in plan) == 1

    def test_enabled_workload_equals_the_plan_and_disabled_is_decode_only(
        self, adapter
    ):
        assert adapter.get_execution_commands("CONFIG_AV1_ENCODER", True) == (
            adapter.get_test_plan(["CONFIG_AV1_ENCODER"])
        )
        disabled = adapter.get_execution_commands("CONFIG_AV1_ENCODER", False)
        assert len(disabled) == 1 and "aomdec" in disabled[0][0]


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

    def test_dca_execution_exercises_and_rejects_the_same_input(self, adapter):
        enabled = adapter.get_execution_commands("decoder=dca", True)
        disabled = adapter.get_execution_commands("decoder=dca", False)

        assert any("prat-dca.dts" in " ".join(command) for command in enabled)
        assert "prat-dca.dts" in " ".join(disabled[0])
        assert "not found" in disabled[0][2]

    def test_dca_test_plan_is_the_positive_workload_only(self, adapter):
        """The 'decoder is absent' assertion is a post-removal check, not
        part of T: run against B_all it would fail by design."""
        plan = adapter.get_test_plan(["decoder=dca"])

        assert plan == adapter.get_execution_commands("decoder=dca", True)
        assert not any("not found" in " ".join(command) for command in plan)


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
        assert "--features" not in cmd
        assert "--no-default-features" in cmd
        assert cmd[:2] == ["cargo", "build"]

    def test_disabling_a_default_feature_preserves_other_defaults(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text(
            "[features]\ndefault = ['tls', 'logging']\ntls = []\nlogging = []\n"
        )
        (tmp_path / "src").mkdir(exist_ok=True)
        adapter = RustAdapter(str(tmp_path))

        cmd = adapter.get_compile_command("tls", False)

        assert "--no-default-features" in cmd
        assert cmd[cmd.index("--features") + 1] == "logging"

    def test_llvm_cov_command(self, adapter):
        enabled = adapter.get_llvm_cov_command("qlog", True, "/tmp/c.lcov")
        assert enabled[:3] == ["cargo", "llvm-cov", "--lib"]
        assert "--features" in enabled and "qlog" in enabled
        assert "--lcov" in enabled
        disabled = adapter.get_llvm_cov_command("qlog", False, "/tmp/c.lcov")
        assert "--no-default-features" in disabled

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
        assert flag == "-DTLS=ON"

        flag = adapter.format_feature_flag("TLS", False)
        assert flag == "-DTLS=OFF"

    def test_compile_command_has_coverage_flags(self, adapter):
        cmd = adapter.get_compile_command("TLS", True)
        assert any("--coverage" in arg for arg in cmd)
        assert cmd[:5] == ["cmake", "-S", ".", "-B", "build"]

    def test_build_commands_configure_then_build(self, adapter):
        commands = adapter.get_build_commands("TLS", True)
        assert commands[0][0] == "cmake"
        assert commands[1] == ["cmake", "--build", "build", "--parallel"]


class TestOpenDDSAdapter:
    @pytest.fixture
    def adapter(self, tmp_path):
        (tmp_path / "configure").touch()
        (tmp_path / "dds").mkdir()
        (tmp_path / "DDS.mwc").touch()
        return OpenDDSAdapter(str(tmp_path))

    def test_toggles_content_filtered_topic(self, adapter):
        enabled = adapter.get_compile_command("content-filtered-topic", True)
        disabled = adapter.get_compile_command("content-filtered-topic", False)

        assert "--content-filtered-topic" in enabled[2]
        assert "--no-content-filtered-topic" in disabled[2]
        assert "--security" not in enabled[2]

    def test_reports_the_actual_mpc_build_system(self, adapter):
        assert adapter.build_system == BuildSystem.MPC

    def test_runs_upstream_content_filtered_topic_test(self, adapter):
        command = adapter.get_execution_commands("content-filtered-topic", True)
        assert "tests/DCPS/ContentFilteredTopic/run_test.pl" in command[0][2]
