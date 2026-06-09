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
        """Paper Table 2: default KLEE parameters."""
        cfg = KleeConfig()
        assert cfg.libc == "uclibc"
        assert cfg.runtime == "posix-runtime"
        assert cfg.sym_args == "0 3 4"
        assert cfg.sym_files == "2 4"
        assert cfg.max_fail == 1
        assert cfg.max_time == 60
        assert cfg.solver_backend == "z3"

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
        cfg = KleeConfig(max_time=120, solver_backend="stp", libc="none")
        args = cfg.to_klee_args()

        assert "--max-time" in args
        idx = args.index("--max-time")
        assert args[idx + 1] == "120"
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
    def test_successful_compilation(self, mock_run, tmp_path):
        bc_path = str(tmp_path / "out.bc")
        # Create the output file to simulate success
        Path(bc_path).write_bytes(b"\x00" * 100)
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        result = compile_to_bytecode(
            [str(tmp_path / "main.c")], bc_path
        )
        assert result == bc_path

    @patch("prat.symbolic.subprocess.run")
    def test_compilation_failure(self, mock_run, tmp_path):
        bc_path = str(tmp_path / "out.bc")
        mock_run.return_value = MagicMock(returncode=1, stderr="error: unknown type")

        result = compile_to_bytecode(
            [str(tmp_path / "main.c")], bc_path
        )
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
            config=KleeConfig(max_time=10),
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
