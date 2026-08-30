from __future__ import annotations

from pathlib import Path

from spatial_ui_agent_server.service_manager import LABEL, launch_agent_payload, service_url


def test_launch_agent_payload_is_laptop_local(tmp_path: Path) -> None:
    root = tmp_path / "server"
    home = tmp_path / "home"
    payload = launch_agent_payload(root, home, "/opt/homebrew/bin:/usr/bin:/bin")

    assert payload["Label"] == LABEL
    assert payload["ProgramArguments"] == [str(root / "scripts" / "run")]
    assert payload["WorkingDirectory"] == str(root)
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] is True
    assert payload["EnvironmentVariables"]["HOME"] == str(home)
    assert "Library/Logs/SpatialUIAgent" in payload["StandardOutPath"]
    assert "axiom" not in str(payload).lower()


def test_service_url_uses_local_loopback_and_configured_port(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SPATIAL_PORT=8766\n", encoding="utf-8")

    assert service_url(tmp_path) == "http://127.0.0.1:8766"
