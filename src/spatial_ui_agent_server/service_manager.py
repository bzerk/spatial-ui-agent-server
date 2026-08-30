from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

LABEL = "io.github.bzerk.spatial-ui-agent-server"
ROOT = Path(__file__).resolve().parents[2]


def environment_value(root: Path, key: str, default: str) -> str:
    env_file = root / ".env"
    if not env_file.exists():
        return default
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return default


def service_url(root: Path) -> str:
    port = environment_value(root, "SPATIAL_PORT", "8765")
    return f"http://127.0.0.1:{port}"


def launch_agent_payload(root: Path, home: Path, path_value: str) -> dict[str, Any]:
    log_dir = home / "Library" / "Logs" / "SpatialUIAgent"
    return {
        "Label": LABEL,
        "ProgramArguments": [str(root / "scripts" / "run")],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "ThrottleInterval": 5,
        "StandardOutPath": str(log_dir / "launchd.stdout.log"),
        "StandardErrorPath": str(log_dir / "launchd.stderr.log"),
        "EnvironmentVariables": {
            "HOME": str(home),
            "PATH": path_value,
            "PYTHONUNBUFFERED": "1",
        },
    }


class ServiceManager:
    def __init__(self, root: Path = ROOT) -> None:
        self.root = root.resolve()
        self.home = Path.home()
        self.domain = f"gui/{os.getuid()}"
        self.target = f"{self.domain}/{LABEL}"
        self.plist = self.home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        self.log_dir = self.home / "Library" / "Logs" / "SpatialUIAgent"

    def launchctl(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["launchctl", *arguments],
            check=check,
            text=True,
        )

    def loaded(self) -> bool:
        result = subprocess.run(
            ["launchctl", "print", self.target],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0

    def write_plist(self) -> None:
        if not (self.root / ".env").exists():
            raise SystemExit("Missing .env; run scripts/configure_demo.py first.")
        self.plist.parent.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        path_parts = os.environ.get("PATH", "").split(":") + [
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
        ]
        path_value = ":".join(dict.fromkeys(path_parts))
        payload = launch_agent_payload(self.root, self.home, path_value)
        with tempfile.NamedTemporaryFile(dir=self.plist.parent, delete=False) as temporary:
            plistlib.dump(payload, temporary, sort_keys=True)
            temporary_path = Path(temporary.name)
        temporary_path.chmod(0o600)
        os.replace(temporary_path, self.plist)

    def wait_for_health(self, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        health_url = service_url(self.root) + "/health"
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(health_url, timeout=1) as response:
                    if response.status == 200:
                        return True
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(0.25)
        return False

    def install(self) -> None:
        self.write_plist()
        if self.loaded():
            self.launchctl("bootout", self.target)
        self.launchctl("bootstrap", self.domain, str(self.plist))
        self.launchctl("kickstart", "-k", self.target)
        if not self.wait_for_health():
            raise SystemExit(f"Service did not become healthy; inspect {self.log_dir}")
        print(f"installed {LABEL}")
        print(f"console {service_url(self.root)}/admin")
        log_file = environment_value(
            self.root, "SPATIAL_LOG_FILE", str(self.root / "data" / "server.log")
        )
        print(f"logs {log_file}")

    def start(self) -> None:
        if not self.plist.exists():
            raise SystemExit("LaunchAgent is not installed; run scripts/service install.")
        if not self.loaded():
            self.launchctl("bootstrap", self.domain, str(self.plist))
        self.launchctl("kickstart", "-k", self.target)
        if not self.wait_for_health():
            raise SystemExit(f"Service did not become healthy; inspect {self.log_dir}")
        print(f"started {LABEL}")

    def stop(self) -> None:
        if self.loaded():
            self.launchctl("bootout", self.target)
        print(f"stopped {LABEL}")

    def restart(self) -> None:
        if not self.loaded():
            self.start()
            return
        self.launchctl("kickstart", "-k", self.target)
        if not self.wait_for_health():
            raise SystemExit(f"Service did not become healthy; inspect {self.log_dir}")
        print(f"restarted {LABEL}")

    def status(self) -> None:
        if not self.loaded():
            raise SystemExit(f"{LABEL} is not loaded")
        self.launchctl("print", self.target)
        health_url = service_url(self.root) + "/health"
        try:
            with urllib.request.urlopen(health_url, timeout=2) as response:
                print(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError) as error:
            raise SystemExit(f"LaunchAgent is loaded but health failed: {error}") from error

    def logs(self) -> None:
        log_file = Path(
            environment_value(self.root, "SPATIAL_LOG_FILE", str(self.root / "data" / "server.log"))
        ).expanduser()
        os.execvp("tail", ["tail", "-n", "120", "-F", str(log_file)])

    def open_console(self) -> None:
        webbrowser.open(service_url(self.root) + "/admin")

    def uninstall(self) -> None:
        self.stop()
        if self.plist.exists():
            self.plist.unlink()
        print(f"removed {self.plist}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the laptop-local Spatial UI Agent")
    parser.add_argument(
        "command",
        choices=("install", "start", "stop", "restart", "status", "logs", "open", "uninstall"),
    )
    args = parser.parse_args()
    manager = ServiceManager()
    getattr(manager, "open_console" if args.command == "open" else args.command)()


if __name__ == "__main__":
    main()
