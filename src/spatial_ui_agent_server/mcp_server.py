from __future__ import annotations

import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import Settings
from .service import SpatialService


def build_mcp(service: SpatialService) -> FastMCP:
    mcp = FastMCP(
        "Rokid Spatial UI Agent",
        json_response=True,
        streamable_http_path="/mcp",
        instructions="Operate local Rokid devices and immutable spatial.surface.v1 revisions.",
    )

    @mcp.tool()
    def devices_list() -> list[dict[str, Any]]:
        """List known devices and their latest seen timestamp."""
        return service.store.all("SELECT * FROM devices ORDER BY last_seen DESC")

    @mcp.tool()
    def surface_get_active() -> dict[str, Any]:
        """Return the active immutable spatial surface manifest."""
        return service.active_surface()["manifest"]

    @mcp.tool()
    async def surface_generate(request: str) -> dict[str, Any]:
        """Generate, validate, store, and activate a new surface."""
        return await service.generate_surface(request)

    @mcp.tool()
    def surface_put(files: list[dict[str, str]]) -> dict[str, Any]:
        """Validate and store UTF-8 surface files without activating them."""
        return service.put_surface(files)

    @mcp.tool()
    def surface_push(device_id: str, revision: str) -> dict[str, Any]:
        """Queue an immutable surface revision for a device."""
        return service.push_surface(device_id, revision)

    @mcp.tool()
    def surface_reset(
        device_id: str | None = None, fixture: str = "constellation"
    ) -> dict[str, Any]:
        """Activate a built-in fixture and optionally push it to a device."""
        package = service.install_fixture(fixture, activate=True)
        result: dict[str, Any] = {"manifest": package.manifest}
        if device_id:
            result["event"] = service.push_surface(device_id, package.revision)
        return result

    def device_action(device_id: str, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        return service.queue_device_event(
            device_id, "device.command", {"command": command, **payload}, str(uuid.uuid4())
        )

    @mcp.tool()
    def device_capture_camera(device_id: str) -> dict[str, Any]:
        """Request a camera capture from a device."""
        return device_action(device_id, "capture_camera", {})

    @mcp.tool()
    def device_capture_display(device_id: str) -> dict[str, Any]:
        """Request a display capture from a device."""
        return device_action(device_id, "capture_display", {})

    @mcp.tool()
    def device_speak(device_id: str, text: str) -> dict[str, Any]:
        """Request bounded text-to-speech on a device."""
        if not text.strip() or len(text) > 1000:
            raise ValueError("text must contain 1-1000 characters")
        return device_action(device_id, "speak", {"text": text})

    return mcp


def main() -> None:
    settings = Settings.from_env()
    service = SpatialService(settings)
    service.initialize()
    build_mcp(service).run(transport="stdio")
