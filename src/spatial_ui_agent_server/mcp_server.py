from __future__ import annotations

import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import Settings
from .guidelines import surface_guidelines_document
from .service import SpatialService


def build_mcp(service: SpatialService) -> FastMCP:
    mcp = FastMCP(
        "Rokid Spatial UI Agent",
        json_response=True,
        streamable_http_path="/mcp",
        instructions=(
            "Operate local Rokid devices and immutable spatial.surface.v1 revisions. "
            "Before authoring or uploading surface files, call surface_guidelines_get and follow "
            "the returned canonical guide. "
            "Before changing a live device, call device_surface_get so edits use the exact "
            "surface reported by that device, then put or generate and push the new revision."
        ),
    )

    @mcp.tool()
    def surface_guidelines_get() -> dict[str, Any]:
        """Return the canonical Rokid UI guide, version, and SHA-256 for surface authoring."""
        return surface_guidelines_document()

    @mcp.tool()
    def devices_list() -> list[dict[str, Any]]:
        """List known devices, latest seen time, and reported loaded surface metadata."""
        return service.devices()

    @mcp.tool()
    def surface_get_active() -> dict[str, Any]:
        """Return the active immutable spatial surface manifest."""
        return service.active_surface()["manifest"]

    @mcp.tool()
    def surface_source_get(revision: str) -> dict[str, Any]:
        """Return the exact UTF-8 files and manifest for an immutable revision."""
        return service.surface_source(revision)

    @mcp.tool()
    def device_surface_get(device_id: str) -> dict[str, Any]:
        """Return the exact source most recently reported as loaded by a device."""
        return service.device_surface(device_id)

    @mcp.tool()
    async def surface_generate(
        request: str,
        device_id: str | None = None,
        base_revision: str | None = None,
    ) -> dict[str, Any]:
        """Generate and store a surface from a device's exact source or a named revision."""
        return await service.generate_surface(
            request, device_id=device_id, base_revision=base_revision
        )

    @mcp.tool()
    async def surface_generate_and_push(device_id: str, request: str) -> dict[str, Any]:
        """Modify the source loaded by a device, then queue the validated revision to it."""
        generated = await service.generate_surface(request, device_id=device_id)
        revision = generated["manifest"]["revision"]
        return {
            **generated,
            "event": service.push_surface(device_id, revision),
        }

    @mcp.tool()
    def surface_put(files: list[dict[str, str]], guidelines_sha256: str) -> dict[str, Any]:
        """Validate authored files after acknowledging the current canonical UI guide."""
        if guidelines_sha256 != surface_guidelines_document()["sha256"]:
            raise ValueError(
                "guidelines_sha256 is missing or stale; call surface_guidelines_get "
                "before authoring"
            )
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
