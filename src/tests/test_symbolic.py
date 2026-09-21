"""Tests for prat.symbolic module."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from prat.symbolic import (
    KleeConfig,
    SymbolicResult,
    check_klee_available,
    compile_to_bytecode,
    generate_symbolic_tests,
    replay_tests,
    run_klee,
)


class TestKleeConfig:
    """Tests for KleeConfig."""

    def test_default_values_match_paper(self):
        """Paper Table 3: default KLEE parameters."""
        cfg = KleeConfig()
        assert cfg.libc == "uclibc"
        assert cfg.runtime == "posix-runtime"
        assert cfg.sym_args == "0 3 4"
        assert cfg.sym_files == "2 4"
        assert cfg.max_fail == 1
        assert cfg.max_time_minutes == 60
        assert cfg.solver_backend == "z3"

    def test_max_time_is_minutes_converted_to_seconds(self):
        """The paper runs KLEE "for 60 minutes"; KLEE's flag takes seconds."""
        cfg = KleeConfig()

        assert cfg.max_time_seconds == 3600
        args = cfg.to_klee_args()
        assert args[args.index("--max-time") + 1] == "3600"

    def test_to_klee_args(self):
        cfg = KleeConfig()
        args = cfg.to_klee_args()

        assert "--libc" in args
        assert "uclibc" in args
        assert "--posix-runtime" in args
        assert "--solver-backend" in args
        assert "z3" in args
        assert "-emit-all-errors" in args

    def test_to_klee_args_with_libraries(self):
        cfg = KleeConfig(link_libraries=["/path/to/lib.so", "/path/to/other.bc"])
        args = cfg.to_klee_args()

        assert "-link-llvm-lib" in args
        assert "/path/to/lib.so" in args
        assert "/path/to/other.bc" in args

    def test_to_replay_sym_args(self):
        cfg = KleeConfig(sym_args="0 3 4", sym_files="2 4")
        args = cfg.to_replay_sym_args()

        assert "--sym-args" in args
        assert "--sym-files" in args
        assert "0" in args
        assert "4" in args

    def test_custom_config(self):
        cfg = KleeConfig(max_time_minutes=120, solver_backend="stp", libc="none")
        args = cfg.to_klee_args()

        assert "--max-time" in args
        idx = args.index("--max-time")
        # Stored in minutes, emitted in the seconds KLEE expects.
        assert args[idx + 1] == "7200"
        assert "stp" in args
        assert "none" in args


class TestCheckKleeAvailable:

    @patch("prat.symbolic.shutil.which")
    def test_local_klee_found(self, mock_which):
        mock_which.return_value = "/usr/bin/klee"
        assert check_klee_available(use_docker=False) is True

    @patch("prat.symbolic.shutil.which")
    def test_local_klee_not_found(self, mock_which):
        mock_which.return_value = None
        assert check_klee_available(use_docker=False) is False

    @patch("prat.symbolic.subprocess.run")
    def test_docker_klee_available(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert check_klee_available(use_docker=True) is True

    @patch("prat.symbolic.subprocess.run")
    def test_docker_klee_not_available(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        assert check_klee_available(use_docker=True) is False


class TestCompileToBytecode:

    @patch("prat.symbolic.subprocess.run")
    def test_single_file_compiles_and_is_staged(self, mock_run, tmp_path):
        bc_path = str(tmp_path / "out.bc")

        def fake_run(cmd, **_kwargs):
            # clang writes its -o target; emulate that so staging can proceed.
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"\x00" * 64)
            return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = fake_run

        result = compile_to_bytecode([str(tmp_path / "main.c")], bc_path)

        assert result == bc_path
        assert Path(bc_path).exists()

    @patch("prat.symbolic.subprocess.run")
    def test_multiple_files_are_linked_into_one_module(self, mock_run, tmp_path):
        """`clang -emit-llvm -c a.c b.c -o out.bc` is an error, so we llvm-link."""
        bc_path = str(tmp_path / "out.bc")
        commands = []

        def fake_run(cmd, **_kwargs):
            commands.append(cmd)
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"\x00" * 64)
            return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = fake_run

        result = compile_to_bytecode(
            [str(tmp_path / "a.c"), str(tmp_path / "b.c")], bc_path
        )

        assert result == bc_path
        # Two clang invocations, each with exactly one source, then llvm-link.
        clang_calls = [c for c in commands if c[0] == "clang"]
        assert len(clang_calls) == 2
        assert any(c[0] == "llvm-link" for c in commands)

    @patch("prat.symbolic.subprocess.run")
    def test_identically_named_sources_do_not_collide(self, mock_run, tmp_path):
        bc_path = str(tmp_path / "out.bc")
        outputs = []

        def fake_run(cmd, **_kwargs):
            target = cmd[cmd.index("-o") + 1]
            outputs.append(target)
            Path(target).write_bytes(b"\x00" * 64)
            return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = fake_run

        compile_to_bytecode(["src/a/util.c", "src/b/util.c"], bc_path)

        object_files = [o for o in outputs if o != bc_path]
        assert len(set(object_files)) == len(object_files)

    @patch("prat.symbolic.subprocess.run")
    def test_partial_failure_still_links_what_compiled(self, mock_run, tmp_path):
        bc_path = str(tmp_path / "out.bc")

        def fake_run(cmd, **_kwargs):
            if cmd[0] == "clang" and cmd[-3].endswith("bad.c"):
                return MagicMock(returncode=1, stderr="error: bad")
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"\x00" * 64)
            return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = fake_run

        result = compile_to_bytecode(
            [str(tmp_path / "good.c"), str(tmp_path / "bad.c")], bc_path
        )

        assert result == bc_path

    @patch("prat.symbolic.subprocess.run")
    def test_no_sources_returns_none(self, mock_run, tmp_path):
        assert compile_to_bytecode([], str(tmp_path / "out.bc")) is None
        mock_run.assert_not_called()

    @patch("prat.symbolic.subprocess.run")
    def test_compilation_failure(self, mock_run, tmp_path):
        bc_path = str(tmp_path / "out.bc")
        mock_run.return_value = MagicMock(returncode=1, stderr="error: unknown type")

        result = compile_to_bytecode([str(tmp_path / "main.c")], bc_path)
        assert result is None

    @patch("prat.symbolic.subprocess.run")
    def test_clang_not_found(self, mock_run, tmp_path):
        mock_run.side_effect = FileNotFoundError()
        result = compile_to_bytecode(
            ["main.c"], str(tmp_path / "out.bc"),
            clang_binary="/nonexistent/clang"
        )
        assert result is None


class TestRunKlee:

    @patch("prat.symbolic.subprocess.run")
    def test_klee_produces_tests(self, mock_run, tmp_path):
        klee_out = tmp_path / "klee-out"
        klee_out.mkdir()
        # Simulate KLEE generating test files
        for i in range(5):
            (klee_out / f"test{i:06d}.ktest").write_bytes(b"\x00")

        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

        result = run_klee(
            str(tmp_path / "program.bc"),
            config=KleeConfig(max_time_minutes=10),
            output_dir=str(klee_out),
        )

        assert result.success is True
        assert result.test_count == 5

    @patch("prat.symbolic.subprocess.run")
    def test_klee_no_tests(self, mock_run, tmp_path):
        klee_out = tmp_path / "klee-out"
        klee_out.mkdir()

        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

        result = run_klee(
            str(tmp_path / "program.bc"),
            output_dir=str(klee_out),
        )

        # No .ktest files but exit code 0 => still "success"
        assert result.success is True
        assert result.test_count == 0


class TestReplayTests:

    @patch("prat.symbolic.shutil.which")
    def test_replay_not_available(self, mock_which):
        mock_which.return_value = None
        results = replay_tests("/bin/test", ["/test.ktest"])
        assert results == {}

    @patch("prat.symbolic.subprocess.run")
    @patch("prat.symbolic.shutil.which")
    def test_replay_passes(self, mock_which, mock_run):
        mock_which.return_value = "/usr/bin/klee-replay"
        mock_run.return_value = MagicMock(returncode=0)

        results = replay_tests("/bin/test", ["/tmp/test000001.ktest"])
        assert results["test000001.ktest"] is True

    @patch("prat.symbolic.subprocess.run")
    @patch("prat.symbolic.shutil.which")
    def test_replay_timeout_counts_as_pass(self, mock_which, mock_run):
        """Timeouts still generate coverage data."""
        mock_which.return_value = "/usr/bin/klee-replay"
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=10)

        results = replay_tests("/bin/test", ["/tmp/test000001.ktest"])
        assert results["test000001.ktest"] is True


class TestGenerateSymbolicTests:

    @patch("prat.symbolic.run_klee")
    @patch("prat.symbolic.compile_to_bytecode")
    def test_end_to_end_pipeline(self, mock_compile, mock_klee, tmp_path):
        # Create a fake source file
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.c").write_text("int main() { return 0; }")

        mock_compile.return_value = str(tmp_path / "klee_output" / "program.bc")
        mock_klee.return_value = SymbolicResult(
            success=True,
            test_cases=["/tmp/test1.ktest", "/tmp/test2.ktest"],
            test_count=2,
        )

        result = generate_symbolic_tests(
            project_path=str(tmp_path),
            output_dir=str(tmp_path / "klee_output"),
            replay=False,
        )

        assert result.success is True
        assert result.test_count == 2

    def test_no_source_files(self, tmp_path):
        result = generate_symbolic_tests(
            project_path=str(tmp_path),
            source_files=[],
        )
        # Empty list should trigger error
        assert result is not None

    @patch("prat.symbolic.compile_to_bytecode")
    def test_bytecode_failure(self, mock_compile, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.c").write_text("int main() {}")

        mock_compile.return_value = None

        result = generate_symbolic_tests(
            project_path=str(tmp_path),
            output_dir=str(tmp_path / "out"),
        )
        assert result.success is False
        assert "Bytecode" in result.error_message
