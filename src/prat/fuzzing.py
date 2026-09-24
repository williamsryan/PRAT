"""
MQTT fuzzing harness for PRAT.

Paper, Evaluation (Correctness): "we built a custom MQTT fuzzing engines [sic]
based on the popular Boofuzz fuzzer. Fuzzing as a testing strategy was not
considered or employed during the design and implementation of PRAT; therefore,
we consider it a useful ``sanity check'' with potential to uncover issues not
otherwise identified."

This module launches a Mosquitto broker built by PRAT, fuzzes it over MQTT, and
reports the line and function coverage the session reached plus any crash the
broker suffered — the columns of the paper's fuzz-testing table.

Two things about interpreting the output. Coverage comes from the broker's own
gcov instrumentation, so the broker must be compiled with ``--coverage``; without
it you get crash data but no coverage. And a crash is only evidence of a
regression relative to a baseline: the paper's variant 0 is the all-features
build, and a crash counts as "introduced by removal" only if variant 0 did not
also exhibit it. :func:`compare_to_baseline` performs that comparison rather than
leaving it to the reader.

Boofuzz is an optional dependency (``pip install 'prat[fuzz]'``);
:func:`check_boofuzz_available` lets callers skip fuzzing instead of failing.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .gcov import load_coverage_dir
from .mapping import coverage_totals, function_totals

#: Default broker port for fuzzing. Deliberately not 1883, so a fuzzing session
#: cannot reach a real broker someone happens to be running locally.
DEFAULT_FUZZ_PORT = 18830


@dataclass
class FuzzResult:
    """Outcome of one fuzzing session against one program variant.

    Fields correspond to the paper's fuzz-testing table: total and covered lines
    with the resulting percentage, the same for functions, and session duration
    in minutes.
    """

    variant: str
    removed_features: list[str] = field(default_factory=list)
    removed_count: int = 0

    total_lines: int = 0
    covered_lines: int = 0
    total_functions: int = 0
    covered_functions: int = 0

    duration_seconds: float = 0.0
    test_cases_sent: int = 0

    #: Crash signatures observed (e.g. "SIGSEGV").
    crashes: list[str] = field(default_factory=list)
    broker_exit_code: int | None = None

    success: bool = False
    error_message: str | None = None

    @property
    def line_coverage_pct(self) -> float | None:
        if self.total_lines == 0:
            return None
        return 100.0 * self.covered_lines / self.total_lines

    @property
    def function_coverage_pct(self) -> float | None:
        if self.total_functions == 0:
            return None
        return 100.0 * self.covered_functions / self.total_functions

    @property
    def duration_minutes(self) -> float:
        return self.duration_seconds / 60.0

    def table_row(self) -> str:
        """Render as one row of the paper's fuzz-testing table."""

        def pct(value: float | None) -> str:
            return f"{value:.1f}%" if value is not None else "n/a"

        return (
            f"{self.removed_count:>3} | {self.total_lines:>6} | "
            f"{self.covered_lines:>6} | {pct(self.line_coverage_pct):>7} | "
            f"{self.total_functions:>5} | {self.covered_functions:>5} | "
            f"{pct(self.function_coverage_pct):>7} | "
            f"{self.duration_minutes:>6.0f}"
        )


@dataclass
class FuzzCampaign:
    """A whole campaign: one FuzzResult per variant, plus the baseline check."""

    results: list[FuzzResult] = field(default_factory=list)
    #: Crashes present in the baseline variant, so they are not attributed to
    #: feature removal.
    baseline_crashes: list[str] = field(default_factory=list)
    #: variant -> crash signatures absent from the baseline.
    introduced_crashes: dict[str, list[str]] = field(default_factory=dict)

    @property
    def any_introduced_crash(self) -> bool:
        return any(self.introduced_crashes.values())

    def table(self) -> str:
        """Render the campaign as the paper's fuzz-testing table."""
        header = (
            "#Rm |  Lines | Covrd |    Cov% |  Fns | Covrd |    Cov% |  Time\n"
            + "-" * 72
        )
        rows = "\n".join(result.table_row() for result in self.results)
        return f"{header}\n{rows}"


def check_boofuzz_available() -> bool:
    """Whether the optional Boofuzz dependency is importable."""
    try:
        import boofuzz  # type: ignore[import-not-found,import-untyped]  # noqa: F401
    except ImportError:
        return False
    return True


# ---------------------------------------------------------------------------
# MQTT protocol definitions
# ---------------------------------------------------------------------------


def define_mqtt_requests(fuzz_payloads: bool = True) -> list[str]:
    """Register the MQTT packets to fuzz with Boofuzz and return their names.

    Covers the control packets a broker parses before and just after a client
    connects, which is where a debloated broker is most likely to diverge:
    CONNECT, PUBLISH, SUBSCRIBE, PINGREQ and DISCONNECT.

    The MQTT "remaining length" field is declared as a Boofuzz sizer over the
    variable-length body, so mutating the body keeps the framing self-consistent
    and the broker actually parses the packet instead of rejecting it on length.
    The length field is itself fuzzable, so inconsistent framing is exercised
    too — just not on every case.

    Args:
        fuzz_payloads: Mutate string fields. Disable to fuzz only header and
            framing fields.

    Returns:
        Request names in the order a session should send them.
    """
    from boofuzz import (
        blocks,
        s_block_end,
        s_block_start,
        s_byte,
        s_initialize,
        s_size,
        s_static,
        s_string,
        s_word,
    )

    # boofuzz keeps requests in a process-global registry and `s_initialize`
    # raises if a name is already present. A campaign fuzzes several variants in
    # one process, so re-registering has to be allowed: drop any previous
    # definitions first.
    for name in (
        "mqtt_connect",
        "mqtt_publish",
        "mqtt_subscribe",
        "mqtt_pingreq",
        "mqtt_disconnect",
    ):
        blocks.REQUESTS.pop(name, None)
    blocks.CURRENT = None

    big_endian = ">"

    # --- CONNECT (packet type 1) -------------------------------------------
    s_initialize("mqtt_connect")
    s_static(b"\x10")  # type 1, flags 0
    s_size("connect_body", length=1, endian=big_endian,
           fuzzable=True, name="remaining_length")
    if s_block_start("connect_body"):
        s_word(4, endian=big_endian, fuzzable=True, name="protocol_name_len")
        s_string("MQTT", size=4, fuzzable=fuzz_payloads, name="protocol_name")
        s_byte(0x04, fuzzable=True, name="protocol_level")  # 4 = MQTT 3.1.1
        s_byte(0x02, fuzzable=True, name="connect_flags")   # clean session
        s_word(60, endian=big_endian, fuzzable=True, name="keep_alive")
        s_word(6, endian=big_endian, fuzzable=True, name="client_id_len")
        s_string("pratfz", fuzzable=fuzz_payloads, name="client_id")
    s_block_end()

    # --- PUBLISH (packet type 3, QoS 0) ------------------------------------
    s_initialize("mqtt_publish")
    s_static(b"\x30")
    s_size("publish_body", length=1, endian=big_endian,
           fuzzable=True, name="remaining_length")
    if s_block_start("publish_body"):
        s_word(9, endian=big_endian, fuzzable=True, name="topic_len")
        s_string("prat/fuzz", fuzzable=fuzz_payloads, name="topic")
        s_string("payload", fuzzable=fuzz_payloads, name="payload")
    s_block_end()

    # --- SUBSCRIBE (packet type 8, requires QoS 1 flags) -------------------
    s_initialize("mqtt_subscribe")
    s_static(b"\x82")
    s_size("subscribe_body", length=1, endian=big_endian,
           fuzzable=True, name="remaining_length")
    if s_block_start("subscribe_body"):
        s_word(1, endian=big_endian, fuzzable=True, name="packet_id")
        s_word(9, endian=big_endian, fuzzable=True, name="filter_len")
        s_string("prat/fuzz", fuzzable=fuzz_payloads, name="topic_filter")
        s_byte(0x00, fuzzable=True, name="requested_qos")
    s_block_end()

    # --- PINGREQ (packet type 12) -----------------------------------------
    s_initialize("mqtt_pingreq")
    s_static(b"\xc0")
    s_byte(0x00, fuzzable=True, name="remaining_length")

    # --- DISCONNECT (packet type 14) --------------------------------------
    s_initialize("mqtt_disconnect")
    s_static(b"\xe0")
    s_byte(0x00, fuzzable=True, name="remaining_length")

    return [
        "mqtt_connect",
        "mqtt_publish",
        "mqtt_subscribe",
        "mqtt_pingreq",
        "mqtt_disconnect",
    ]


# ---------------------------------------------------------------------------
# Broker lifecycle
# ---------------------------------------------------------------------------


def _write_broker_config(config_path: Path, port: int) -> None:
    """Write a minimal broker config: listen on the fuzz port, allow anonymous."""
    config_path.write_text(
        "\n".join([
            f"listener {port}",
            "allow_anonymous true",
            "persistence false",
            "log_dest none",
            "",
        ]),
        encoding="utf-8",
    )


def _wait_for_port(port: int, timeout: float = 10.0) -> bool:
    """Block until the broker is accepting connections, or the timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.5)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


def _classify_exit(returncode: int | None) -> str | None:
    """Map a broker exit code to a crash signature, or None if it exited cleanly."""
    if returncode is None or returncode >= 0:
        return None
    try:
        return signal.Signals(-returncode).name
    except ValueError:
        return f"signal {-returncode}"


# ---------------------------------------------------------------------------
# Fuzzing a single variant
# ---------------------------------------------------------------------------


def fuzz_variant(
    broker_binary: str,
    project_path: str,
    variant: str,
    removed_features: list[str] | None = None,
    port: int = DEFAULT_FUZZ_PORT,
    duration_seconds: int = 600,
    coverage_tool: str = "gcov",
    source_directories: tuple[str, ...] = ("src", "lib"),
    fuzz_payloads: bool = True,
    work_dir: str | None = None,
) -> FuzzResult:
    """Fuzz one broker variant and measure the coverage the session reached.

    Args:
        broker_binary: Path to the coverage-instrumented broker executable.
        project_path: Project root, where the ``.gcda`` files land.
        variant: Label for this variant (e.g. ``variant_3``).
        removed_features: Features removed to produce this variant.
        port: Port the broker should listen on.
        duration_seconds: Wall-clock budget for the session.
        coverage_tool: ``gcov`` or an ``llvm-cov`` variant.
        source_directories: Directories to collect coverage from.
        fuzz_payloads: Mutate string fields as well as framing.
        work_dir: Directory for the broker config, logs and coverage output.

    Returns:
        FuzzResult with coverage, duration, and any crash signature.
    """
    result = FuzzResult(
        variant=variant,
        removed_features=list(removed_features or ()),
        removed_count=len(removed_features or ()),
    )

    if not check_boofuzz_available():
        result.error_message = (
            "boofuzz is not installed; install it with \"pip install 'prat[fuzz]'\""
        )
        return result

    if not os.path.isfile(broker_binary):
        result.error_message = f"Broker binary not found: {broker_binary}"
        return result

    work = Path(work_dir or (Path(project_path) / f".prat_fuzz_{variant}"))
    work.mkdir(parents=True, exist_ok=True)

    config_path = work / "broker.conf"
    _write_broker_config(config_path, port)

    # Clear stale profile data so the measured coverage belongs to this session.
    _reset_gcda(project_path)

    broker: subprocess.Popen | None = None
    start = time.time()

    try:
        broker = subprocess.Popen(
            [broker_binary, "-c", str(config_path)],
            cwd=project_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        if not _wait_for_port(port):
            result.error_message = (
                f"Broker did not start listening on port {port} within 10s"
            )
            return result

        result.test_cases_sent = _run_boofuzz_session(
            port=port,
            duration_seconds=duration_seconds,
            fuzz_payloads=fuzz_payloads,
            work_dir=work,
        )

    except (OSError, subprocess.SubprocessError) as exc:
        result.error_message = f"Fuzzing session failed: {exc}"
        return result

    finally:
        result.duration_seconds = time.time() - start
        if broker is not None:
            crash = _shutdown_broker(broker)
            result.broker_exit_code = broker.returncode
            if crash:
                result.crashes.append(crash)

    # The broker must exit for gcov to flush .gcda, which _shutdown_broker
    # ensures before we collect.
    coverage_dir = work / "coverage"
    collected = _collect_coverage(
        project_path, coverage_tool, source_directories, coverage_dir
    )

    if collected:
        parsed = load_coverage_dir(str(coverage_dir))
        result.covered_lines, result.total_lines = coverage_totals(parsed)
        result.covered_functions, result.total_functions = function_totals(parsed)
    else:
        result.error_message = (
            "Fuzzing ran but no coverage was produced — is the broker built "
            "with --coverage?"
        )

    result.success = result.error_message is None
    return result


def _run_boofuzz_session(
    port: int,
    duration_seconds: int,
    fuzz_payloads: bool,
    work_dir: Path,
) -> int:
    """Drive the Boofuzz session and return the number of test cases sent."""
    from boofuzz import Session, Target, TCPSocketConnection, s_get

    names = define_mqtt_requests(fuzz_payloads=fuzz_payloads)

    session = Session(
        target=Target(
            connection=TCPSocketConnection("127.0.0.1", port, send_timeout=2.0,
                                           recv_timeout=2.0),
        ),
        db_filename=str(work_dir / "boofuzz.db"),
        # Keep going after a connection error: a broker that drops a malformed
        # connection is behaving correctly, not crashing.
        ignore_connection_issues=True,
        sleep_time=0.0,
        receive_data_after_fuzz=True,
        keep_web_open=False,
        web_port=None,
    )

    # CONNECT is the root; the remaining packets follow it, so each is fuzzed on
    # an established connection rather than in isolation.
    root = names[0]
    session.connect(s_get(root))
    for name in names[1:]:
        session.connect(s_get(root), s_get(name))

    deadline = time.time() + duration_seconds

    def _budget_exhausted(*_args: object, **_kwargs: object) -> None:
        if time.time() > deadline:
            raise KeyboardInterrupt("fuzzing time budget reached")

    session.register_post_test_case_callback(_budget_exhausted)

    # The budget callback stops the session by raising, which is the only hook
    # boofuzz offers for "stop after N seconds".
    with contextlib.suppress(KeyboardInterrupt):
        session.fuzz()

    return int(getattr(session, "total_mutant_index", 0) or 0)


def _shutdown_broker(broker: subprocess.Popen) -> str | None:
    """Stop the broker so gcov flushes, and report a crash signature if any.

    gcov writes ``.gcda`` only when the process exits normally, so the broker is
    asked to terminate and given time to do so before being killed. A broker
    killed by SIGKILL here has not crashed — it failed to shut down — so that
    case is distinguished from a genuine fault signal.
    """
    if broker.poll() is not None:
        # Already dead: it either exited or faulted during the session.
        return _classify_exit(broker.returncode)

    broker.terminate()
    try:
        broker.wait(timeout=15)
    except subprocess.TimeoutExpired:
        broker.kill()
        broker.wait(timeout=10)
        return None  # forced kill, not a fault

    return _classify_exit(broker.returncode)


def _reset_gcda(project_path: str) -> None:
    """Delete stale .gcda files so coverage reflects only the coming session."""
    for gcda in Path(project_path).rglob("*.gcda"):
        try:
            gcda.unlink()
        except OSError:
            continue


def _collect_coverage(
    project_path: str,
    coverage_tool: str,
    source_directories: tuple[str, ...],
    coverage_dir: Path,
) -> list[str]:
    """Run gcov over the broker's profile data and gather the .gcov files."""
    coverage_dir.mkdir(parents=True, exist_ok=True)
    project = Path(project_path)
    collected: list[str] = []

    base = f"{coverage_tool} gcov" if "llvm-cov" in coverage_tool else coverage_tool

    for directory_name in source_directories:
        directory = project / directory_name
        if not directory.is_dir():
            continue

        subprocess.run(
            f"{base} -f *.gcno",
            shell=True,
            cwd=str(directory),
            capture_output=True,
            text=True,
        )

        for item in directory.iterdir():
            if item.suffix != ".gcov":
                continue
            destination = coverage_dir / item.name
            try:
                shutil.move(str(item), str(destination))
                collected.append(str(destination))
            except OSError:
                continue

    return collected


def compare_to_baseline(campaign: FuzzCampaign) -> FuzzCampaign:
    """Attribute crashes to removal only when the baseline did not show them.

    The paper's variant 0 is the all-features build, and serves "as a baseline
    for #crashes present in the source prior to feature removal". A crash that
    variant 0 also exhibits is pre-existing, not a regression.
    """
    if not campaign.results:
        return campaign

    baseline = campaign.results[0]
    campaign.baseline_crashes = list(baseline.crashes)
    known = set(baseline.crashes)

    for result in campaign.results[1:]:
        new = [crash for crash in result.crashes if crash not in known]
        if new:
            campaign.introduced_crashes[result.variant] = new

    return campaign
