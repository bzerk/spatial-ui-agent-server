from __future__ import annotations

import asyncio
import html
import io
import json
import re
import uuid
import wave
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from .auth import BearerGate
from .config import Settings
from .db import now
from .discovery import Discovery
from .mcp_server import build_mcp
from .service import SpatialService

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ACK_STATUSES = {"downloaded", "loaded", "rendered", "failed"}
LOOPBACK = {"127.0.0.1", "::1"}


def _turn_json(turn: dict) -> dict:
    return {
        "schema": "spatial.turn.v1",
        "turn_id": turn.get("id"),
        "event_id": turn.get("event_id"),
        "device_id": turn.get("device_id"),
        "status": turn.get("status"),
        "transcript": turn.get("transcript"),
        "surface_revision": turn.get("surface_revision"),
        "error": turn.get("error"),
        "created_at": turn.get("created_at"),
        "updated_at": turn.get("updated_at"),
    }


def create_app(
    settings: Settings | None = None, service: SpatialService | None = None
) -> Starlette:
    settings = settings or Settings.from_env()
    service = service or SpatialService(settings)
    discovery = Discovery(settings)
    background: set[asyncio.Task] = set()
    mcp = build_mcp(service)
    mcp_app = mcp.streamable_http_app()

    async def health(_: Request) -> JSONResponse:
        active = service.store.active_surface()
        return JSONResponse(
            {
                "status": "ok",
                "contract": "spatial.surface.v1",
                "activeSurface": active["revision"] if active else None,
                "transcriber": service.worker.health(),
                "mdns": "enabled" if settings.mdns_enabled else "disabled",
            }
        )

    async def admin(request: Request) -> HTMLResponse:
        client = request.client.host if request.client else ""
        if client not in LOOPBACK:
            return HTMLResponse("loopback only", status_code=403)
        turns = service.store.all("SELECT * FROM turns ORDER BY created_at DESC LIMIT 20")
        devices = service.store.all("SELECT * FROM devices ORDER BY last_seen DESC LIMIT 20")
        rows = (
            "".join(
                f"<tr><td>{html.escape(item['id'])}</td><td>{html.escape(item['device_id'])}</td>"
                f"<td>{html.escape(item['status'])}</td><td>{html.escape(item['updated_at'])}</td></tr>"
                for item in turns
            )
            or "<tr><td colspan=4>No turns</td></tr>"
        )
        device_rows = (
            "".join(
                f"<li>{html.escape(item['id'])}<small>{html.escape(item['last_seen'])}</small></li>"
                for item in devices
            )
            or "<li>No devices connected</li>"
        )
        page = f"""<!doctype html>
        <html><head><meta charset=utf-8><title>Spatial Agent</title>
        <style>
        body{{font:14px ui-monospace,monospace;margin:32px;max-width:1000px;
        color:#17221b;background:#edf0e8}}
        h1{{font-size:24px}}
        section{{background:#fff;padding:18px;margin:16px 0;border:1px solid #b7c1b6}}
        table{{width:100%;border-collapse:collapse}}
        td,th{{padding:8px;text-align:left;border-bottom:1px solid #ddd}}
        li{{margin:8px 0}}small{{display:block;color:#68746b}}
        </style></head><body>
        <h1>Spatial Agent</h1>
        <section><h2>Devices</h2><ul>{device_rows}</ul></section>
        <section><h2>Recent turns</h2><table><thead><tr>
        <th>ID</th><th>Device</th><th>Status</th><th>Updated</th>
        </tr></thead><tbody>{rows}</tbody></table></section>
        </body></html>"""
        return HTMLResponse(page)

    async def create_turn(request: Request) -> JSONResponse:
        async with request.form(max_files=2, max_fields=4, max_part_size=10 * 1024 * 1024) as form:
            event_id = str(form.get("event_id", ""))
            device_id = str(form.get("device_id", ""))
            audio = form.get("audio")
            image = form.get("photo") or form.get("image")
            context_raw = str(form.get("context", "{}"))
            try:
                uuid.UUID(event_id)
                context_value = json.loads(context_raw)
                if not isinstance(context_value, dict) or len(context_raw) > 16_384:
                    raise ValueError
            except (ValueError, json.JSONDecodeError):
                return JSONResponse(
                    {"error": "event_id must be a UUID and context a JSON object"}, status_code=422
                )
            if not IDENTIFIER.fullmatch(device_id):
                return JSONResponse({"error": "invalid event_id or device_id"}, status_code=422)
            if not hasattr(audio, "read"):
                return JSONResponse({"error": "audio WAV is required"}, status_code=422)
            audio_bytes = await audio.read()  # type: ignore[union-attr]
            if (
                len(audio_bytes) > 8 * 1024 * 1024
                or audio_bytes[:4] != b"RIFF"
                or audio_bytes[8:12] != b"WAVE"
            ):
                return JSONResponse(
                    {"error": "audio must be a WAV no larger than 8 MiB"}, status_code=422
                )
            try:
                with wave.open(io.BytesIO(audio_bytes), "rb") as wav:
                    valid_wav = (
                        wav.getnchannels() == 1
                        and wav.getsampwidth() == 2
                        and wav.getframerate() == 16000
                        and wav.getcomptype() == "NONE"
                    )
            except (wave.Error, EOFError):
                valid_wav = False
            if not valid_wav:
                return JSONResponse(
                    {"error": "audio must be PCM16 mono 16 kHz WAV"}, status_code=422
                )
            image_bytes = None
            if hasattr(image, "read"):
                image_bytes = await image.read()  # type: ignore[union-attr]
                if len(image_bytes) > 4 * 1024 * 1024 or image_bytes[:3] != b"\xff\xd8\xff":
                    return JSONResponse(
                        {"error": "image must be a JPEG no larger than 4 MiB"}, status_code=422
                    )
        turn_id = str(uuid.uuid4())
        turn_dir = service.upload_dir / turn_id
        turn_dir.mkdir(parents=True, exist_ok=False)
        audio_path = turn_dir / "audio.wav"
        audio_path.write_bytes(audio_bytes)
        image_path = turn_dir / "image.jpg" if image_bytes else None
        if image_path and image_bytes:
            image_path.write_bytes(image_bytes)
        created = now()
        turn, inserted = service.store.create_turn(
            {
                "id": turn_id,
                "event_id": event_id,
                "device_id": device_id,
                "audio_path": str(audio_path),
                "image_path": str(image_path) if image_path else None,
                "context": context_value,
                "created_at": created,
            }
        )
        if not inserted:
            for path in turn_dir.iterdir():
                path.unlink()
            turn_dir.rmdir()
        else:
            task = asyncio.create_task(service.process_turn(turn_id))
            background.add(task)
            task.add_done_callback(background.discard)
        response = _turn_json(turn)
        response = {key: response[key] for key in ("schema", "turn_id", "event_id", "status")}
        return JSONResponse(response, status_code=202)

    async def get_turn(request: Request) -> JSONResponse:
        turn = service.store.one(
            "SELECT * FROM turns WHERE id=?", (request.path_params["turn_id"],)
        )
        return (
            JSONResponse(_turn_json(turn), status_code=200)
            if turn
            else JSONResponse({"error": "not_found"}, status_code=404)
        )

    async def get_surface(request: Request):
        surface = service.surface(request.path_params["revision"])
        if not surface:
            return JSONResponse({"error": "not_found"}, status_code=404)
        return FileResponse(
            surface["zip_path"],
            media_type="application/zip",
            filename=f"{surface['revision']}.zip",
            headers={
                "ETag": f'"{surface["revision"]}"',
                "Cache-Control": "public, immutable, max-age=31536000",
            },
        )

    async def device_events(websocket: WebSocket) -> None:
        device_id = websocket.path_params["device_id"]
        if not IDENTIFIER.fullmatch(device_id):
            await websocket.close(code=4400)
            return
        try:
            cursor = max(0, int(websocket.query_params.get("cursor", "0")))
        except ValueError:
            await websocket.close(code=4400)
            return
        await websocket.accept()
        service.store.touch_device(device_id)
        try:
            while True:
                for event in service.store.events_after(device_id, cursor):
                    await websocket.send_json(
                        {
                            "schema": "spatial.event.v1",
                            "event_id": event["event_id"],
                            "sequence": event["seq"],
                            "device_id": event["device_id"],
                            "type": event["kind"],
                            "created_at": event["created_at"],
                            "payload": event["payload"],
                        }
                    )
                    cursor = event["seq"]
                try:
                    message = await asyncio.wait_for(websocket.receive_json(), timeout=1.0)
                except TimeoutError:
                    continue
                if message.get("schema") == "spatial.ack.v1" or message.get("type") == "ack":
                    status = message.get("state", message.get("status"))
                    if status not in ACK_STATUSES:
                        await websocket.send_json({"type": "error", "error": "invalid_ack_status"})
                        continue
                    accepted = service.store.acknowledge(
                        device_id,
                        str(message.get("event_id", "")),
                        status,
                        message.get("revision"),
                        str(message.get("detail", ""))[:500] or None,
                    )
                    if not accepted:
                        await websocket.send_json({"type": "error", "error": "unknown_event"})
                elif message.get("type") == "ping":
                    service.store.touch_device(device_id)
                    await websocket.send_json({"type": "pong", "cursor": cursor})
                else:
                    await websocket.send_json({"type": "error", "error": "unsupported_message"})
        except WebSocketDisconnect:
            return

    device_api = Starlette(
        routes=[
            Route("/turns", create_turn, methods=["POST"]),
            Route("/turns/{turn_id}", get_turn, methods=["GET"]),
            Route("/surfaces/{revision}.zip", get_surface, methods=["GET"]),
            WebSocketRoute("/devices/{device_id}/events", device_events),
        ]
    )

    @asynccontextmanager
    async def lifespan(_: Starlette):
        service.initialize()
        if settings.whisper_prewarm:
            try:
                await service.worker.start()
            except Exception as error:
                service.worker.last_error = str(error)
        if settings.mdns_enabled:
            try:
                await asyncio.to_thread(discovery.start)
            except Exception:
                discovery.stop()
        async with mcp.session_manager.run():
            yield
        for task in background:
            task.cancel()
        if background:
            await asyncio.gather(*background, return_exceptions=True)
        await service.worker.stop()
        await asyncio.to_thread(discovery.stop)

    return Starlette(
        routes=[
            Route("/health", health),
            Route("/admin", admin),
            Mount("/v1", app=BearerGate(device_api, settings.device_token_file)),
            Mount("/", app=BearerGate(mcp_app, settings.mcp_token_file, settings.mcp_allowlist)),
        ],
        lifespan=lifespan,
    )


app = create_app()
