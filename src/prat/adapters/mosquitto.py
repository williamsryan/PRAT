"""
Mosquitto project adapter for PRAT.

On Linux: Make-based build with WITH_FEATURE=yes/no flags.
On macOS: CMake-based build (Makefile requires CMake on Mac OS X).
"""


from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from ..compilation import BuildSystem
from .base import ProjectAdapter


def _is_macos() -> bool:
    return platform.system() == "Darwin"


class MosquittoAdapter(ProjectAdapter):
    """
    Adapter for Mosquitto MQTT broker.

    Linux: Make + WITH_FEATURE=yes/no + gcov
    macOS: CMake + -DWITH_FEATURE=ON/OFF + gcov
    """

    @property
    def build_system(self) -> BuildSystem:
        return BuildSystem.CMAKE if _is_macos() else BuildSystem.MAKE

    @property
    def coverage_tool(self) -> str:
        return "gcov"

    @property
    def source_directories(self) -> list[str]:
        return ["src", "lib"]

    def normalize_feature_name(self, raw_option: str) -> str:
        """Strip the ``WITH_`` prefix that :meth:`format_feature_flag` re-adds.

        Discovery reports build options verbatim (``WITH_TLS``), while this
        adapter's flag formatter builds ``WITH_<name>``, so passing the raw
        option straight through would produce ``WITH_WITH_TLS``.
        """
        upper = raw_option.upper()
        return upper[len("WITH_"):] if upper.startswith("WITH_") else upper

    def _build_dir(self) -> Path:
        d = self.project_path / "build"
        d.mkdir(exist_ok=True)
        return d

    def get_compile_command(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True,
    ) -> list[str]:
        if _is_macos():
            # Use -B/-S so cmake can run from project root (cwd=project_path)
            cmd = ["cmake", "-B", "build", "-S", ".", "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
                   "-DWITH_PLUGINS=OFF", "-DDOCUMENTATION=OFF"]
            cmd.append(self.format_feature_flag(feature, enabled))
            if with_coverage:
                cmd.extend([
                    "-DCMAKE_BUILD_TYPE=Debug",
                    "-DCMAKE_C_FLAGS=--coverage",
                    "-DCMAKE_CXX_FLAGS=--coverage",
                ])
            return cmd
        else:
            cmd = ["make", "binary", "-j"]
            if with_coverage:
                cmd.append("WITH_COVERAGE=yes")
            cmd.append(self.format_feature_flag(feature, enabled))
            return cmd

    def get_build_commands(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True,
    ) -> list[list[str]]:
        if _is_macos():
            return [
                self.get_compile_command(feature, enabled, with_coverage),
                ["make", "-C", "build", "-j"],
            ]
        return [self.get_compile_command(feature, enabled, with_coverage)]

    def get_clean_command(self) -> list[str]:
        if _is_macos():
            # Remove .gcda files too so stale counters don't cause "cannot merge" errors
            return ["bash", "-c", "cmake --build build --target clean 2>/dev/null; find build -name '*.gcda' -delete 2>/dev/null; true"]
        return ["make", "clean"]

    def get_test_command(self) -> list[str] | None:
        if _is_macos():
            return ["ctest", "--output-on-failure"]
        return ["make", "utest", "-j", "WITH_COVERAGE=yes"]

    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        if _is_macos():
            flag_value = "ON" if enabled else "OFF"
            return f"-DWITH_{feature.upper()}={flag_value}"
        flag_value = "yes" if enabled else "no"
        return f"WITH_{feature.upper()}={flag_value}"

    def get_binary_path(self) -> str | None:
        """Get path to mosquitto binary."""
        candidates = [
            self.project_path / "build" / "src" / "mosquitto",
            self.project_path / "src" / "mosquitto",
        ]
        for binary in candidates:
            if binary.exists():
                return str(binary)
        return None

    def validate_project(self) -> bool:
        """Validate this is a Mosquitto project."""
        # Check for Mosquitto-specific files
        makefile = self.project_path / "Makefile"
        config_mk = self.project_path / "config.mk"
        src_dir = self.project_path / "src"

        return (
            makefile.exists() and
            config_mk.exists() and
            src_dir.exists()
        )

    def _write_listener_config(self, use_tls: bool) -> str:
        """Write a broker config with a plain listener, or a TLS one, and return its path."""
        root = self.project_path.resolve()
        name = "prat_tls" if use_tls else "prat_plain"
        config_path = root / "build" / f"{name}.conf"
        port = 18883 if use_tls else 11883

        lines = ["allow_anonymous true\n", f"listener {port}\n"]
        if use_tls:
            ssl_dir = self._ensure_test_certificates()
            lines += [
                f"cafile {ssl_dir}/ca.crt\n",
                f"certfile {ssl_dir}/server.crt\n",
                f"keyfile {ssl_dir}/server.key\n",
            ]

        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("".join(lines))
        return str(config_path)

    def _ensure_test_certificates(self) -> Path:
        """A CA and a ``localhost`` server certificate under ``build/prat_ssl``.

        Mosquitto ships test certificates in ``test/ssl``, but the ones in the
        2.0.x tags have expired, so a client that verifies them fails with
        "certificate expired" and the TLS session contributes no coverage.
        Mosquitto's own test harness regenerates them; PRAT generates its own
        into the build directory instead, leaving the project tree untouched.
        """
        ssl_dir = self.project_path.resolve() / "build" / "prat_ssl"
        server_crt = ssl_dir / "server.crt"
        if server_crt.exists():
            return ssl_dir
        ssl_dir.mkdir(parents=True, exist_ok=True)
        ext_file = ssl_dir / "server.ext"
        ext_file.write_text("subjectAltName=DNS:localhost,IP:127.0.0.1\n")
        subj = "/O=PRAT test/CN="
        # Only options both OpenSSL and LibreSSL accept: the SAN goes through
        # -extfile at signing time rather than -addext / -copy_extensions.
        commands = [
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30",
             "-subj", f"{subj}PRAT test CA",
             "-keyout", str(ssl_dir / "ca.key"), "-out", str(ssl_dir / "ca.crt")],
            ["openssl", "req", "-newkey", "rsa:2048", "-nodes",
             "-subj", f"{subj}localhost",
             "-keyout", str(ssl_dir / "server.key"), "-out", str(ssl_dir / "server.csr")],
            ["openssl", "x509", "-req", "-days", "30", "-in", str(ssl_dir / "server.csr"),
             "-CA", str(ssl_dir / "ca.crt"), "-CAkey", str(ssl_dir / "ca.key"),
             "-CAcreateserial", "-extfile", str(ext_file), "-out", str(server_crt)],
        ]
        for command in commands:
            subprocess.run(command, check=True, capture_output=True, text=True)
        return ssl_dir

    def _broker_session(self, use_tls: bool) -> list[str]:
        """One command: start the broker, publish once, SIGTERM it.

        The clean SIGTERM matters: gcov's atexit handler is what writes the
        .gcda files, so a killed broker leaves no coverage. The trap runs it on
        every exit path, including a failing client, so a build in which the
        session cannot succeed (a TLS listener in a build without TLS) still
        stops its broker instead of leaving it holding the port and the output
        pipes open until the timeout.
        """
        root = self.project_path.resolve()
        broker = str(root / "build" / "src" / "mosquitto")
        pub = str(root / "build" / "client" / "mosquitto_pub")
        config_path = self._write_listener_config(use_tls)
        port = 18883 if use_tls else 11883

        if use_tls:
            ssl_dir = root / "build" / "prat_ssl"
            client_cmd = (
                f"{pub} --cafile {ssl_dir}/ca.crt"
                f" -h localhost -p {port} -t prat/test -m hello"
            )
        else:
            client_cmd = f"{pub} -h localhost -p {port} -t prat/test -m hello"

        script = (
            f"set -e\n"
            f"{broker} -c {config_path} >/dev/null 2>&1 &\n"
            f"BROKER_PID=$!\n"
            f"trap 'kill -TERM $BROKER_PID 2>/dev/null; wait $BROKER_PID 2>/dev/null' EXIT\n"
            f"sleep 1\n"
            f"kill -0 $BROKER_PID\n"
            f"{client_cmd}\n"
        )
        return ["bash", "-c", script]

    def get_test_plan(self, features: list[str]) -> list[list[str]]:
        """The fixed T for Mosquitto.

        Linux: the project's unit tests (``make utest``), which do not depend on
        the build's feature set.

        macOS: two broker sessions, one on a plain listener and one on a TLS
        listener. The plain session runs against every build; the TLS session
        can only run where TLS is compiled in, so against B_TLS it fails (the
        broker rejects ``cafile``) and is tolerated, and L_TLS still contains
        the plain session's coverage instead of being empty.
        """
        if not _is_macos():
            test_cmd = self.get_test_command()
            return [test_cmd] if test_cmd else []
        return [
            self._broker_session(use_tls=False),
            self._broker_session(use_tls=True),
        ]

    def get_execution_commands(self, feature: str, enabled: bool) -> list:
        """
        Polarity-specific workload, used for post-removal verification.

        Linux: unit tests via make utest.
        macOS: start broker briefly with appropriate config, connect a client,
               then SIGTERM the broker so gcda files are flushed on clean exit.
        """
        if not _is_macos():
            test_cmd = self.get_test_command()
            return [test_cmd] if test_cmd else []

        use_tls = feature.upper() == "TLS" and enabled
        return [self._broker_session(use_tls)]
