"""
Mosquitto project adapter for PRAT.

On Linux: Make-based build with WITH_FEATURE=yes/no flags.
On macOS: CMake-based build (Makefile requires CMake on Mac OS X).
"""

import platform
from pathlib import Path
from typing import List, Optional

from ..compilation import BuildSystem
from .base import ProjectAdapter


def _is_macos() -> bool:
    return platform.system() == "Darwin"


class MosquittoAdapter(ProjectAdapter):
    """
    Adapter for Mosquitto MQTT broker.

    Linux: Make + WITH_FEATURE=yes/no + llvm-cov-9
    macOS: CMake + -DWITH_FEATURE=ON/OFF + gcov
    """

    @property
    def build_system(self) -> BuildSystem:
        return BuildSystem.CMAKE if _is_macos() else BuildSystem.MAKE

    @property
    def coverage_tool(self) -> str:
        return "gcov" if _is_macos() else "llvm-cov-9"

    @property
    def source_directories(self) -> List[str]:
        return ["src", "lib"]

    def _build_dir(self) -> Path:
        d = self.project_path / "build"
        d.mkdir(exist_ok=True)
        return d

    def get_compile_command(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True,
    ) -> List[str]:
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
    ) -> List[List[str]]:
        if _is_macos():
            return [
                self.get_compile_command(feature, enabled, with_coverage),
                ["make", "-C", "build", "-j"],
            ]
        return [self.get_compile_command(feature, enabled, with_coverage)]

    def get_clean_command(self) -> List[str]:
        if _is_macos():
            # Remove .gcda files too so stale counters don't cause "cannot merge" errors
            return ["bash", "-c", "cmake --build build --target clean 2>/dev/null; find build -name '*.gcda' -delete 2>/dev/null; true"]
        return ["make", "clean"]

    def get_test_command(self) -> Optional[List[str]]:
        if _is_macos():
            return ["ctest", "--output-on-failure"]
        return ["make", "utest", "-j", "WITH_COVERAGE=yes"]

    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        if _is_macos():
            flag_value = "ON" if enabled else "OFF"
            return f"-DWITH_{feature.upper()}={flag_value}"
        flag_value = "yes" if enabled else "no"
        return f"WITH_{feature.upper()}={flag_value}"

    def get_binary_path(self) -> Optional[str]:
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

    def _write_mosquitto_config(self, feature: str, enabled: bool) -> str:
        """Write a minimal mosquitto.conf for the PRAT test run and return its path."""
        root = self.project_path.resolve()
        ssl_dir = root / "test" / "ssl"
        config_path = root / "build" / f"prat_{feature.lower()}_{int(enabled)}.conf"

        use_tls = feature.upper() == "TLS" and enabled and ssl_dir.exists()
        port = 18883 if use_tls else 11883

        lines = ["allow_anonymous true\n", f"listener {port}\n"]
        if use_tls:
            lines += [
                f"cafile {ssl_dir}/test-root-ca.crt\n",
                f"certfile {ssl_dir}/server.crt\n",
                f"keyfile {ssl_dir}/server.key\n",
            ]

        config_path.write_text("".join(lines))
        return str(config_path)

    def get_execution_commands(self, feature: str, enabled: bool) -> list:
        """
        Get commands to exercise Mosquitto for dynamic coverage.

        Linux: unit tests via make utest.
        macOS: start broker briefly with appropriate config, connect a client,
               then SIGTERM the broker so gcda files are flushed on clean exit.
        """
        if not _is_macos():
            test_cmd = self.get_test_command()
            return [test_cmd] if test_cmd else []

        root = self.project_path.resolve()
        broker = str(root / "build" / "src" / "mosquitto")
        pub = str(root / "build" / "client" / "mosquitto_pub")
        ssl_dir = root / "test" / "ssl"
        config_path = self._write_mosquitto_config(feature, enabled)

        use_tls = feature.upper() == "TLS" and enabled and ssl_dir.exists()
        port = 18883 if use_tls else 11883
        ssl_dir_str = str(ssl_dir)

        if use_tls:
            client_cmd = (
                f"{pub} --cafile {ssl_dir_str}/test-root-ca.crt --insecure"
                f" -h localhost -p {port} -t prat/test -m hello || true"
            )
        else:
            client_cmd = f"{pub} -h localhost -p {port} -t prat/test -m hello || true"

        # Start broker, wait for it to be ready, run a client publish, then shut down
        # cleanly via SIGTERM so the gcov atexit handler writes .gcda files.
        script = (
            f"set -e\n"
            f"{broker} -c {config_path} &\n"
            f"BROKER_PID=$!\n"
            f"sleep 1\n"
            f"{client_cmd}\n"
            f"kill -TERM $BROKER_PID\n"
            f"wait $BROKER_PID || true\n"
        )
        return [["bash", "-c", script]]
