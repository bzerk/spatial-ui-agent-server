from __future__ import annotations

import asyncio
import hmac
import io
import json
import logging
import re
import secrets
import uuid
import wave
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
)
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from .admin_console import read_log_tail, render_admin_console
from .auth import BearerGate
from .config import Settings
from .db import now
from .discovery import Discovery
from .mcp_server import build_mcp
from .service import SpatialService

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ACK_STATUSES = {"downloaded", "loaded", "rendered", "failed"}
LOOPBACK = {"127.0.0.1", "::1"}
LOGGER = logging.getLogger(__name__)


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
    operator_jobs: dict[str, dict] = {}
    admin_csrf_token = secrets.token_urlsafe(32)
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
                "lanDiscovery": (
                    f"udp:{settings.lan_discovery_port}"
                    if settings.lan_discovery_enabled
                    else "disabled"
                ),
            }
        )

    def is_loopback(request: Request) -> bool:
        return bool(request.client and request.client.host in LOOPBACK)

    async def admin(request: Request) -> HTMLResponse:
        if not is_loopback(request):
            return HTMLResponse("loopback only", status_code=403)
        return HTMLResponse(render_admin_console(admin_csrf_token))

    async def favicon(_: Request) -> Response:
        return Response(status_code=204)

    async def admin_state(request: Request) -> JSONResponse:
        if not is_loopback(request):
            return JSONResponse({"error": "loopback_only"}, status_code=403)
        active = service.store.active_surface()
        turns = service.store.all(
            "SELECT id,device_id,status,transcript,error,created_at,updated_at "
            "FROM turns ORDER BY created_at DESC LIMIT 20"
        )
        devices = service.devices()[:20]
        events = service.store.all(
            "SELECT e.seq,e.event_id,e.device_id,e.kind,e.created_at,"
            "GROUP_CONCAT(a.status, ',') AS ack_status "
            "FROM device_events e LEFT JOIN acknowledgements a ON a.event_id=e.event_id "
            "GROUP BY e.event_id ORDER BY e.seq DESC LIMIT 40"
        )
        surfaces = service.store.all(
            "SELECT revision,source,created_at FROM surfaces ORDER BY created_at DESC LIMIT 20"
        )
        jobs = sorted(operator_jobs.values(), key=lambda item: item["created_at"], reverse=True)[
            :20
        ]
        return JSONResponse(
            {
                "status": "ok",
                "port": settings.port,
                "active_surface": active["revision"] if active else None,
                "transcriber": service.worker.health(),
                "lan_discovery": (
                    f"udp:{settings.lan_discovery_port}"
                    if settings.lan_discovery_enabled
                    else "disabled"
                ),
                "devices": devices,
                "turns": turns,
                "events": events,
                "acknowledgements": service.store.all(
                    "SELECT * FROM acknowledgements ORDER BY created_at DESC LIMIT 40"
                ),
                "surfaces": surfaces,
                "jobs": jobs,
                "log_file": str(settings.log_file),
            }
        )

    async def admin_logs(request: Request) -> PlainTextResponse:
        if not is_loopback(request):
            return PlainTextResponse("loopback only", status_code=403)
        return PlainTextResponse(read_log_tail(settings.log_file))

    async def run_operator_generation(job_id: str, device_id: str, request_text: str) -> None:
        job = operator_jobs[job_id]
        try:
            job["status"] = "designing"
            generated = await service.generate_surface(request_text, device_id=device_id)
            job["status"] = "pushing"
            revision = generated["manifest"]["revision"]
            event = service.push_surface(device_id, revision)
            service.queue_device_event(
                device_id,
                "device.command",
                {"command": "speak", "text": generated["summary"]},
                f"operator:{job_id}:speak",
            )
            job.update(status="ready", revision=revision, event_id=event["event_id"])
            LOGGER.info("operator generation ready job=%s revision=%s", job_id, revision)
        except Exception as error:
            job.update(status="failed", error=str(error)[:500])
            LOGGER.exception("operator generation failed job=%s", job_id)

    async def admin_action(request: Request) -> JSONResponse:
        if not is_loopback(request):
            return JSONResponse({"error": "loopback_only"}, status_code=403)
        supplied_token = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(supplied_token, admin_csrf_token):
            return JSONResponse({"error": "invalid_csrf_token"}, status_code=403)
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "invalid_json"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"error": "invalid_payload"}, status_code=400)
        action = str(payload.get("action", ""))
        device_id = str(payload.get("device_id", ""))
        if not IDENTIFIER.fullmatch(device_id):
            return JSONResponse({"error": "select_a_device"}, status_code=422)

        LOGGER.info("operator action=%s device=%s", action, device_id)
        if action == "generate":
            request_text = " ".join(str(payload.get("request", "")).split())
            if not request_text or len(request_text) > 4000:
                return JSONResponse(
                    {"error": "request_must_be_1_to_4000_characters"}, status_code=422
                )
            job_id = str(uuid.uuid4())
            operator_jobs[job_id] = {
                "id": job_id,
                "device_id": device_id,
                "request": request_text,
                "status": "queued",
                "created_at": now(),
            }
            task = asyncio.create_task(run_operator_generation(job_id, device_id, request_text))
            background.add(task)
            task.add_done_callback(background.discard)
            return JSONResponse(
                {"message": "Generation started.", "job_id": job_id}, status_code=202
            )

        if action == "push-active":
            active = service.active_surface()
            event = service.push_surface(device_id, active["revision"])
            return JSONResponse({"message": "Active surface queued.", "event": event})

        fixture_by_action = {
            "reset-constellation": "constellation",
            "reset-brick-breaker": "brick-breaker",
        }
        if action in fixture_by_action:
            package = service.install_fixture(fixture_by_action[action], activate=True)
            event = service.push_surface(device_id, package.revision)
            return JSONResponse({"message": "Fixture queued.", "event": event})

        command_by_action = {
            "capture-camera": "capture_camera",
            "capture-display": "capture_display",
        }
        if action in command_by_action:
            event = service.queue_device_event(
                device_id,
                "device.command",
                {"command": command_by_action[action]},
            )
            return JSONResponse({"message": "Capture command queued.", "event": event})

        if action == "speak":
            text = " ".join(str(payload.get("text", "")).split())
            if not text or len(text) > 1000:
                return JSONResponse({"error": "text_must_be_1_to_1000_characters"}, status_code=422)
            event = service.queue_device_event(
                device_id,
                "device.command",
                {"command": "speak", "text": text},
            )
            return JSONResponse({"message": "Speech queued.", "event": event})

        return JSONResponse({"error": "unsupported_action"}, status_code=422)

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
                if message.get("schema") == "spatial.runtime.snapshot.v1":
                    try:
                        result = service.register_device_runtime(
                            device_id=device_id,
                            source_kind=str(message.get("source_kind", "unknown"))[:80],
                            url=str(message.get("url", ""))[:500],
                            revision=(
                                str(message["revision"])
                                if message.get("revision") is not None
                                else None
                            ),
                            files=(
                                message.get("files")
                                if isinstance(message.get("files"), list)
                                else None
                            ),
                        )
                    except ValueError as error:
                        await websocket.send_json(
                            {
                                "schema": "spatial.runtime.snapshot.rejected.v1",
                                "error": str(error)[:500],
                            }
                        )
                    else:
                        await websocket.send_json(
                            {
                                "schema": "spatial.runtime.snapshot.accepted.v1",
                                "revision": result["revision"],
                            }
                        )
                elif message.get("schema") == "spatial.ack.v1" or message.get("type") == "ack":
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
        if settings.mdns_enabled or settings.lan_discovery_enabled:
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
            Route("/favicon.ico", favicon),
            Route("/apple-touch-icon.png", favicon),
            Route("/apple-touch-icon-precomposed.png", favicon),
            Route("/admin", admin),
            Route("/admin/state", admin_state),
            Route("/admin/logs", admin_logs),
            Route("/admin/actions", admin_action, methods=["POST"]),
            Mount("/v1", app=BearerGate(device_api, settings.device_token_file)),
            Mount("/", app=BearerGate(mcp_app, settings.mcp_token_file, settings.mcp_allowlist)),
        ],
        lifespan=lifespan,
    )


app = create_app()
