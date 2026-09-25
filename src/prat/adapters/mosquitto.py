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

    PLAIN_PORT = 11883
    TLS_PORT = 18883

    def _write_listener_config(self, name: str, port: int, extra: list[str]) -> str:
        """Write a broker config under ``build/`` and return its path.

        Every config carries a string-valued global option (``pid_file``, inert
        when the broker is not daemonised). Without one, the generic string
        parser (``conf__parse_string`` -> ``misc__trimblanks``) runs only for
        the TLS listeners' ``cafile``/``certfile``/``keyfile`` and so lands in
        D_TLS although it is not TLS code.
        """
        root = self.project_path.resolve()
        config_path = root / "build" / f"{name}.conf"
        lines = [
            "allow_anonymous true\n",
            f"pid_file {root}/build/{name}.pid\n",
            f"listener {port}\n",
            *[f"{line}\n" for line in extra],
        ]
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("".join(lines))
        return str(config_path)

    def _tls_listener_lines(self, ssl_dir: Path, *extra: str) -> list[str]:
        return [
            f"cafile {ssl_dir}/ca.crt",
            f"certfile {ssl_dir}/server.crt",
            f"keyfile {ssl_dir}/server.key",
            *extra,
        ]

    def _ensure_test_certificates(self) -> Path:
        """The certificate set T needs, generated under ``build/prat_ssl``.

        Mosquitto ships test certificates in ``test/ssl``, but the ones in the
        2.0.x tags have expired, so a client that verifies them fails with
        "certificate expired" and the TLS session contributes no coverage.
        Mosquitto's own test harness regenerates them; PRAT generates its own
        into the build directory instead, leaving the project tree untouched.

        Files: ``ca.crt``/``ca.key`` (the trusted CA), ``server.crt``/``.key``
        (``localhost``, SAN for ``127.0.0.1``), ``client.crt``/``.key`` (signed
        by the CA, for mutual TLS), ``other_ca.crt`` (an unrelated CA, for the
        wrong-CA probe) and ``capath/<hash>.0`` (the CA in ``--capath`` layout).
        The ``ready`` marker is written last so a partial directory left by an
        interrupted run is regenerated rather than trusted.
        """
        ssl_dir = self.project_path.resolve() / "build" / "prat_ssl"
        marker = ssl_dir / "ready"
        if marker.exists():
            return ssl_dir
        ssl_dir.mkdir(parents=True, exist_ok=True)
        capath = ssl_dir / "capath"
        capath.mkdir(exist_ok=True)
        ext_file = ssl_dir / "server.ext"
        ext_file.write_text("subjectAltName=DNS:localhost,IP:127.0.0.1\n")
        subj = "/O=PRAT test/CN="

        def run(command: list[str]) -> str:
            return subprocess.run(command, check=True, capture_output=True, text=True).stdout

        def self_signed(stem: str, cn: str) -> None:
            run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30",
                 "-subj", f"{subj}{cn}",
                 "-keyout", str(ssl_dir / f"{stem}.key"), "-out", str(ssl_dir / f"{stem}.crt")])

        def signed_by_ca(stem: str, cn: str, ext: Path | None) -> None:
            # Only options both OpenSSL and LibreSSL accept: the SAN goes through
            # -extfile at signing time rather than -addext / -copy_extensions.
            run(["openssl", "req", "-newkey", "rsa:2048", "-nodes", "-subj", f"{subj}{cn}",
                 "-keyout", str(ssl_dir / f"{stem}.key"), "-out", str(ssl_dir / f"{stem}.csr")])
            run(["openssl", "x509", "-req", "-days", "30", "-in", str(ssl_dir / f"{stem}.csr"),
                 "-CA", str(ssl_dir / "ca.crt"), "-CAkey", str(ssl_dir / "ca.key"),
                 "-CAcreateserial", *(["-extfile", str(ext)] if ext else []),
                 "-out", str(ssl_dir / f"{stem}.crt")])

        self_signed("ca", "PRAT test CA")
        self_signed("other_ca", "PRAT unrelated CA")
        signed_by_ca("server", "localhost", ext_file)
        signed_by_ca("client", "prat-client", None)
        ca_hash = run(["openssl", "x509", "-noout", "-subject_hash",
                       "-in", str(ssl_dir / "ca.crt")]).strip()
        (capath / f"{ca_hash}.0").write_bytes((ssl_dir / "ca.crt").read_bytes())
        marker.write_text("v2\n")
        return ssl_dir

    def _session(self, config_path: str, body: str) -> list[str]:
        """One command: start the broker on ``config_path``, run ``body``, SIGTERM it.

        The clean SIGTERM matters: gcov's atexit handler is what writes the
        .gcda files, so a killed broker leaves no coverage. The trap runs it on
        every exit path, including a failing client, so a build in which the
        session cannot succeed (a TLS listener in a build without TLS) still
        stops its broker instead of leaving it holding the port and the output
        pipes open until the timeout.
        """
        root = self.project_path.resolve()
        broker = str(root / "build" / "src" / "mosquitto")
        script = (
            f"set -e\n"
            f"{broker} -c {config_path} >/dev/null 2>&1 &\n"
            f"BROKER_PID=$!\n"
            f"trap 'kill -TERM $BROKER_PID 2>/dev/null; wait $BROKER_PID 2>/dev/null' EXIT\n"
            f"sleep 1\n"
            f"kill -0 $BROKER_PID\n"
            f"{body}"
        )
        return ["bash", "-c", script]

    def _pub_sub(self, pub: str, sub: str, port: int, client_opts: str,
                 host: str = "localhost") -> str:
        """Subscribe, publish one message, wait for the subscriber to receive it."""
        return (
            f"{sub} -h {host} -p {port} {client_opts} -t prat/test -C 1 -W 5 &\n"
            f"SUB_PID=$!\n"
            f"sleep 1\n"
            f"{pub} -h {host} -p {port} {client_opts} -t prat/test -m hello\n"
            f"wait $SUB_PID\n"
        )

    def _macos_test_plan(self) -> list[list[str]]:
        root = self.project_path.resolve()
        pub = str(root / "build" / "client" / "mosquitto_pub")
        sub = str(root / "build" / "client" / "mosquitto_sub")
        ssl = self._ensure_test_certificates()
        tls = self._tls_listener_lines(ssl)
        cafile = f"--cafile {ssl}/ca.crt"
        plain_port, tls_port = self.PLAIN_PORT, self.TLS_PORT

        def must_fail(command: str) -> str:
            # Under ``set -e`` a ``!`` command never aborts the script, so an
            # expected failure that unexpectedly succeeds is made explicit.
            return f"if {command}; then exit 1; fi\n"

        plain = self._write_listener_config("prat_plain", plain_port, [])
        tls_default = self._write_listener_config("prat_tls", tls_port, tls)
        tls_options = self._write_listener_config(
            "prat_tls_options", tls_port,
            self._tls_listener_lines(ssl, "tls_version tlsv1.2", "ciphers HIGH:!aNULL"),
        )
        tls_mutual = self._write_listener_config(
            "prat_tls_mutual", tls_port,
            self._tls_listener_lines(ssl, "require_certificate true",
                                     "use_subject_as_username true"),
        )
        tls_bad_cert = self._write_listener_config(
            "prat_tls_bad_certfile", tls_port,
            [f"cafile {ssl}/ca.crt", f"certfile {ssl}/does-not-exist.crt",
             f"keyfile {ssl}/server.key"],
        )
        broker = str(root / "build" / "src" / "mosquitto")

        return [
            # 1. Plain listener: subscribe + publish. Runs against every build.
            self._session(plain, self._pub_sub(pub, sub, plain_port, "")),
            # 2. TLS listener with default protocol/ciphers: subscribe + publish.
            self._session(tls_default, self._pub_sub(pub, sub, tls_port, cafile)),
            # 3. TLS listener pinned to TLS 1.2 and a cipher list; the client
            #    pins the same, skips hostname verification and connects by IP.
            self._session(
                tls_options,
                self._pub_sub(pub, sub, tls_port,
                              f"{cafile} --tls-version tlsv1.2 --ciphers HIGH --insecure",
                              host="127.0.0.1"),
            ),
            # 4. Mutual TLS: the broker requires a client certificate and takes
            #    the username from its subject.
            self._session(
                tls_mutual,
                self._pub_sub(pub, sub, tls_port,
                              f"{cafile} --cert {ssl}/client.crt --key {ssl}/client.key"),
            ),
            # 5. The CA supplied as a directory (--capath) instead of a file.
            self._session(
                tls_default,
                f"{pub} -h localhost -p {tls_port} --capath {ssl}/capath"
                f" -t prat/test -m hello\n",
            ),
            # 6. Handshakes that must fail, driving the TLS error paths on both
            #    sides: a plain client on the TLS port, a client trusting an
            #    unrelated CA, and a client whose cafile does not exist.
            self._session(
                tls_default,
                must_fail(f"{pub} -h localhost -p {tls_port} -t prat/test -m hello")
                + must_fail(f"{pub} -h localhost -p {tls_port} --cafile {ssl}/other_ca.crt"
                            f" -t prat/test -m hello")
                + must_fail(f"{pub} -h localhost -p {tls_port} --cafile {ssl}/missing.crt"
                            f" -t prat/test -m hello"),
            ),
            # 7. A broker whose certfile does not exist must refuse to start.
            #    In a build without TLS ``certfile`` is only a warning, so the
            #    broker starts and this command fails there: recorded, tolerated
            #    against B_TLS, and part of the verification reference.
            ["bash", "-c",
             f"{broker} -c {tls_bad_cert} >/dev/null 2>&1 &\n"
             f"BROKER_PID=$!\n"
             f"sleep 1\n"
             f"if kill -0 $BROKER_PID 2>/dev/null; then\n"
             f"  kill -TERM $BROKER_PID; wait $BROKER_PID 2>/dev/null; exit 1\n"
             f"fi\n"
             f"wait $BROKER_PID 2>/dev/null && exit 1 || true\n"],
        ]

    def get_test_plan(self, features: list[str]) -> list[list[str]]:
        """The fixed T for Mosquitto; it does not depend on ``features``.

        Linux: the project's unit tests (``make utest``), which do not depend on
        the build's feature set.

        macOS: seven broker sessions (see :meth:`_macos_test_plan`): a plain
        listener, three TLS listeners (defaults, pinned version and ciphers,
        mutual TLS), a ``--capath`` client, three handshakes that must fail,
        and a broker that must refuse a missing certificate. Every session runs
        against every build. Against B_TLS the TLS sessions fail (the client
        refuses ``--cafile``) and are tolerated; the plain session guarantees
        L_TLS is not empty. The expected-failure sessions exist so that the TLS
        error branches execute in B_all and become part of D_TLS instead of
        remaining guards of code no test reaches.
        """
        if not _is_macos():
            test_cmd = self.get_test_command()
            return [test_cmd] if test_cmd else []
        return self._macos_test_plan()

    def get_execution_commands(self, feature: str, enabled: bool) -> list:
        """The workload no longer depends on polarity: this is the fixed T."""
        return self.get_test_plan([feature])
