#!/usr/bin/env python3
"""Configure a laptop-local server and Android client without printing secrets."""

from __future__ import annotations

import argparse
import secrets
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLIENT = Path.home() / "AndroidStudioProjects" / "RokidWebXRShell"
DEFAULT_WORKER = Path(shutil.which("arux-whisper-worker") or ROOT / "tools/arux-whisper-worker")
DEFAULT_MODEL = Path.home() / "Library/Caches/spatial-ui-agent-server/models/ggml-base.en.bin"


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


def write_server_env(port: int, worker: Path, model: Path) -> None:
    data = ROOT / "data"
    log_file = Path.home() / "Library" / "Logs" / "SpatialUIAgent" / "server.log"
    device_token = data / "device.token"
    mcp_token = data / "mcp.token"
    token_at(device_token)
    token_at(mcp_token)
    codex = shutil.which("codex") or "codex"
    lines = [
        f"SPATIAL_DATA_DIR={data}",
        f"SPATIAL_LOG_FILE={log_file}",
        "SPATIAL_LOG_MAX_BYTES=5242880",
        "SPATIAL_LOG_BACKUP_COUNT=3",
        "SPATIAL_HOST=0.0.0.0",
        f"SPATIAL_PORT={port}",
        f"SPATIAL_DEVICE_TOKEN_FILE={device_token}",
        f"SPATIAL_MCP_TOKEN_FILE={mcp_token}",
        "SPATIAL_MCP_ALLOWLIST=127.0.0.1,::1",
        "SPATIAL_MDNS_ENABLED=false",
        'SPATIAL_MDNS_NAME="Rokid Spatial Agent"',
        "SPATIAL_MDNS_ADDRESS=",
        "SPATIAL_LAN_DISCOVERY_ENABLED=true",
        "SPATIAL_LAN_DISCOVERY_PORT=8767",
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


def write_client_properties(client: Path) -> None:
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
            "WEBXR_SERVICE_BASE_URL": "",
            "WEBXR_SERVICE_TOKEN": token,
            "WEBXR_DEVICE_ID": existing.get("WEBXR_DEVICE_ID", ""),
        }
    )
    order = ["sdk.dir", "WEBXR_SERVICE_BASE_URL", "WEBXR_SERVICE_TOKEN", "WEBXR_DEVICE_ID"]
    path.write_text("".join(f"{key}={existing[key]}\n" for key in order), encoding="utf-8")
    path.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--client", type=Path, default=DEFAULT_CLIENT)
    parser.add_argument("--worker", type=Path, default=DEFAULT_WORKER)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()
    required = {"client": args.client, "transcriber": args.worker, "model": args.model}
    missing = [f"{name}: {path}" for name, path in required.items() if not path.exists()]
    if missing:
        raise SystemExit("Missing required path(s):\n" + "\n".join(missing))
    write_server_env(args.port, args.worker.resolve(), args.model.resolve())
    write_client_properties(args.client.resolve())
    print(f"Configured address-free laptop discovery on UDP 8767 -> HTTP {args.port}")
    print("Device and MCP credentials were written to ignored, mode-0600 files.")
    print("Install the persistent laptop service with: ./scripts/service install")


if __name__ == "__main__":
    main()
