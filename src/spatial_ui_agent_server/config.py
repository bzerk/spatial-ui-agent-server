from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    host: str
    port: int
    public_base_url: str
    device_token_file: Path
    mcp_token_file: Path
    mcp_allowlist: tuple[str, ...]
    mdns_enabled: bool
    mdns_name: str
    mdns_address: str | None
    transcriber_bin: Path
    transcriber_fallback_bin: Path | None
    whisper_model: Path
    whisper_prewarm: bool
    transcriber_fallback: str
    codex_bin: str
    codex_model: str
    codex_reasoning: str
    codex_timeout_seconds: int

    @classmethod
    def from_env(cls) -> Settings:
        data_dir = Path(os.getenv("SPATIAL_DATA_DIR", "./data")).expanduser().resolve()
        fallback = os.getenv("SPATIAL_TRANSCRIBER_FALLBACK_BIN", "")
        return cls(
            data_dir=data_dir,
            host=os.getenv("SPATIAL_HOST", "0.0.0.0"),
            port=int(os.getenv("SPATIAL_PORT", "8765")),
            public_base_url=os.getenv("SPATIAL_PUBLIC_BASE_URL", "http://localhost:8765").rstrip(
                "/"
            ),
            device_token_file=Path(
                os.getenv("SPATIAL_DEVICE_TOKEN_FILE", str(data_dir / "device.token"))
            ).expanduser(),
            mcp_token_file=Path(
                os.getenv("SPATIAL_MCP_TOKEN_FILE", str(data_dir / "mcp.token"))
            ).expanduser(),
            mcp_allowlist=tuple(
                item.strip()
                for item in os.getenv("SPATIAL_MCP_ALLOWLIST", "127.0.0.1,::1").split(",")
                if item.strip()
            ),
            mdns_enabled=_bool("SPATIAL_MDNS_ENABLED", True),
            mdns_name=os.getenv("SPATIAL_MDNS_NAME", "Rokid Spatial Agent"),
            mdns_address=os.getenv("SPATIAL_MDNS_ADDRESS") or None,
            transcriber_bin=Path(
                os.getenv("SPATIAL_TRANSCRIBER_BIN", "arux-whisper-worker")
            ).expanduser(),
            transcriber_fallback_bin=Path(fallback).expanduser() if fallback else None,
            whisper_model=Path(
                os.getenv("SPATIAL_WHISPER_MODEL", "./models/ggml-base.en.bin")
            ).expanduser(),
            whisper_prewarm=_bool("SPATIAL_WHISPER_PREWARM", True),
            transcriber_fallback=os.getenv("SPATIAL_TRANSCRIBER_FALLBACK", "fail"),
            codex_bin=os.getenv("SPATIAL_CODEX_BIN", "codex"),
            codex_model=os.getenv("SPATIAL_CODEX_MODEL", "gpt-5.6-sol"),
            codex_reasoning=os.getenv("SPATIAL_CODEX_REASONING", "low"),
            codex_timeout_seconds=int(os.getenv("SPATIAL_CODEX_TIMEOUT_SECONDS", "600")),
        )
