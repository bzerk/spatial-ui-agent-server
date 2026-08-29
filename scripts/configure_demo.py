#!/usr/bin/env python3
"""Configure a laptop-local server and Android client without printing secrets."""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import socket
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLIENT = Path.home() / "AndroidStudioProjects" / "RokidWebXRShell"
DEFAULT_WORKER = Path(shutil.which("arux-whisper-worker") or ROOT / "tools/arux-whisper-worker")
DEFAULT_MODEL = (
    Path.home() / "Library/Caches/spatial-ui-agent-server/models/ggml-base.en.bin"
)


def local_address() -> str:
    override = os.getenv("SPATIAL_DEMO_ADDRESS")
    if override:
        return override
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect(("1.1.1.1", 53))
        return str(probe.getsockname()[0])


def token_at(path: Path) -> str:
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if not token:
            raise SystemExit(f"Token file is empty: {path}")
        return token
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(secrets.token_urlsafe(48) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path.read_text(encoding="utf-8").strip()


def write_server_env(address: str, port: int, worker: Path, model: Path) -> None:
    data = ROOT / "data"
    device_token = data / "device.token"
    mcp_token = data / "mcp.token"
    token_at(device_token)
    token_at(mcp_token)
    codex = shutil.which("codex") or "codex"
    lines = [
        f"SPATIAL_DATA_DIR={data}",
        "SPATIAL_HOST=0.0.0.0",
        f"SPATIAL_PORT={port}",
        f"SPATIAL_PUBLIC_BASE_URL=http://{address}:{port}",
        f"SPATIAL_DEVICE_TOKEN_FILE={device_token}",
        f"SPATIAL_MCP_TOKEN_FILE={mcp_token}",
        "SPATIAL_MCP_ALLOWLIST=127.0.0.1,::1",
        "SPATIAL_MDNS_ENABLED=true",
        'SPATIAL_MDNS_NAME="Rokid Spatial Agent"',
        f"SPATIAL_MDNS_ADDRESS={address}",
        f"SPATIAL_TRANSCRIBER_BIN={worker}",
        "SPATIAL_TRANSCRIBER_FALLBACK_BIN=",
        f"SPATIAL_WHISPER_MODEL={model}",
        "SPATIAL_WHISPER_PREWARM=true",
        "SPATIAL_TRANSCRIBER_FALLBACK=fail",
        f"SPATIAL_CODEX_BIN={codex}",
        "SPATIAL_CODEX_MODEL=gpt-5.6-sol",
        "SPATIAL_CODEX_REASONING=low",
        "SPATIAL_CODEX_TIMEOUT_SECONDS=600",
    ]
    (ROOT / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_client_properties(client: Path, address: str, port: int) -> None:
    token = token_at(ROOT / "data/device.token")
    sdk = Path.home() / "Library/Android/sdk"
    path = client / "local.properties"
    existing: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                existing[key.strip()] = value.strip()
    existing.update(
        {
            "sdk.dir": str(sdk),
            "WEBXR_SERVICE_BASE_URL": f"http://{address}:{port}",
            "WEBXR_SERVICE_TOKEN": token,
            "WEBXR_DEVICE_ID": existing.get("WEBXR_DEVICE_ID", ""),
        }
    )
    order = ["sdk.dir", "WEBXR_SERVICE_BASE_URL", "WEBXR_SERVICE_TOKEN", "WEBXR_DEVICE_ID"]
    path.write_text("".join(f"{key}={existing[key]}\n" for key in order), encoding="utf-8")
    path.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", default=None, help="LAN address advertised to glasses")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--client", type=Path, default=DEFAULT_CLIENT)
    parser.add_argument("--worker", type=Path, default=DEFAULT_WORKER)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()
    address = args.address or local_address()
    required = {"client": args.client, "transcriber": args.worker, "model": args.model}
    missing = [f"{name}: {path}" for name, path in required.items() if not path.exists()]
    if missing:
        raise SystemExit("Missing required path(s):\n" + "\n".join(missing))
    write_server_env(address, args.port, args.worker.resolve(), args.model.resolve())
    write_client_properties(args.client.resolve(), address, args.port)
    print(f"Configured laptop-local demo at http://{address}:{args.port}")
    print("Device and MCP credentials were written to ignored, mode-0600 files.")


if __name__ == "__main__":
    main()
