from __future__ import annotations

from pathlib import Path

import pytest

from spatial_ui_agent_server.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    device_token = tmp_path / "device.token"
    mcp_token = tmp_path / "mcp.token"
    device_token.write_text("device-secret\n", encoding="utf-8")
    mcp_token.write_text("mcp-secret\n", encoding="utf-8")
    return Settings(
        data_dir=tmp_path / "data",
        host="127.0.0.1",
        port=8765,
        public_base_url="http://127.0.0.1:8765",
        device_token_file=device_token,
        mcp_token_file=mcp_token,
        mcp_allowlist=("127.0.0.1", "::1", "testclient"),
        mdns_enabled=False,
        mdns_name="Test Agent",
        mdns_address=None,
        transcriber_bin=Path("missing-worker"),
        transcriber_fallback_bin=None,
        whisper_model=tmp_path / "missing-model.bin",
        whisper_prewarm=False,
        transcriber_fallback="fixture",
        codex_bin="codex",
        codex_model="gpt-5.6-sol",
        codex_reasoning="low",
        codex_timeout_seconds=5,
    )
