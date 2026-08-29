#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from spatial_ui_agent_server.auth import read_token
from spatial_ui_agent_server.config import Settings


async def call(tool: str, arguments: dict[str, object]) -> None:
    settings = Settings.from_env()
    token = read_token(settings.mcp_token_file)
    if not token:
        raise SystemExit("generate the local MCP token before calling tools")
    url = f"http://127.0.0.1:{settings.port}/mcp"
    timeout = httpx.Timeout(settings.codex_timeout_seconds + 120)
    async with (
        httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        ) as client,
        streamable_http_client(url, http_client=client) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool(tool, arguments)
    print(json.dumps(result.model_dump(mode="json"), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Call an authorized local spatial MCP tool")
    parser.add_argument("tool")
    parser.add_argument("arguments", nargs="?", default="{}", help="JSON object")
    args = parser.parse_args()
    arguments = json.loads(args.arguments)
    if not isinstance(arguments, dict):
        raise SystemExit("arguments must decode to a JSON object")
    asyncio.run(call(args.tool, arguments))


if __name__ == "__main__":
    main()
