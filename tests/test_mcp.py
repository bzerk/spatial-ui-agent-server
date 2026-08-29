from __future__ import annotations

import os
import sys

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from starlette.testclient import TestClient

from spatial_ui_agent_server.api import create_app
from spatial_ui_agent_server.mcp_server import build_mcp
from spatial_ui_agent_server.service import SpatialService


@pytest.mark.asyncio
async def test_official_mcp_registers_required_tools(settings) -> None:
    service = SpatialService(settings)
    service.initialize()
    mcp = build_mcp(service)
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}
    assert names == {
        "devices_list",
        "surface_get_active",
        "surface_generate",
        "surface_put",
        "surface_push",
        "surface_reset",
        "device_capture_camera",
        "device_capture_display",
        "device_speak",
    }


def test_streamable_http_requires_mcp_token_and_initializes(settings) -> None:
    service = SpatialService(settings)
    app = create_app(settings, service)
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1"},
        },
    }
    accept = "application/json, text/event-stream"
    with TestClient(app, base_url="http://localhost:8765") as client:
        assert client.post("/mcp", json=request, headers={"Accept": accept}).status_code == 401
        response = client.post(
            "/mcp",
            json=request,
            headers={
                "Accept": accept,
                "Authorization": "Bearer mcp-secret",
            },
        )
        assert response.status_code == 200
        assert response.json()["result"]["serverInfo"]["name"] == "Rokid Spatial UI Agent"


@pytest.mark.asyncio
async def test_official_stdio_client_round_trip(settings) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "SPATIAL_DATA_DIR": str(settings.data_dir / "stdio"),
            "SPATIAL_MDNS_ENABLED": "false",
            "SPATIAL_WHISPER_PREWARM": "false",
            "SPATIAL_TRANSCRIBER_BIN": "missing-worker",
            "SPATIAL_WHISPER_MODEL": str(settings.whisper_model),
        }
    )
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from spatial_ui_agent_server.mcp_server import main; main()"],
        env=environment,
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        result = await session.list_tools()
        assert "surface_get_active" in {tool.name for tool in result.tools}


def test_speech_summary_rejects_code_and_is_bounded(settings) -> None:
    service = SpatialService(settings)
    assert service.speech_summary("A clean yaw game is ready.") == "A clean yaw game is ready."
    assert service.speech_summary("`const code = true`") == "Your spatial surface is ready."
    assert len(service.speech_summary("word " * 100)) <= 160
