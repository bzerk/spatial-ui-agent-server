#!/usr/bin/env python3
from __future__ import annotations

import json

import httpx

from spatial_ui_agent_server.auth import read_token
from spatial_ui_agent_server.config import Settings


def main() -> None:
    settings = Settings.from_env()
    base_url = f"http://127.0.0.1:{settings.port}"
    device_token = read_token(settings.device_token_file)
    mcp_token = read_token(settings.mcp_token_file)
    if not device_token or not mcp_token:
        raise SystemExit("generate both local token files before smoke testing")
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "spatial-smoke", "version": "1"},
        },
    }
    accept = "application/json, text/event-stream"
    with httpx.Client(base_url=base_url, timeout=30) as client:
        health = client.get("/health")
        device_denied = client.get("/v1/turns/missing")
        mcp_denied = client.post("/mcp", json=initialize, headers={"Accept": accept})
        mcp = client.post(
            "/mcp",
            json=initialize,
            headers={"Accept": accept, "Authorization": f"Bearer {mcp_token}"},
        )
    health.raise_for_status()
    mcp.raise_for_status()
    if device_denied.status_code != 401 or mcp_denied.status_code != 401:
        raise SystemExit("an unauthenticated protected endpoint did not return 401")
    print(
        json.dumps(
            {
                "health": health.json()["status"],
                "transcriber": health.json()["transcriber"]["status"],
                "deviceUnauthenticated": device_denied.status_code,
                "mcpUnauthenticated": mcp_denied.status_code,
                "mcpServer": mcp.json()["result"]["serverInfo"]["name"],
            }
        )
    )


if __name__ == "__main__":
    main()
