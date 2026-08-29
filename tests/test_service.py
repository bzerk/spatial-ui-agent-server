from __future__ import annotations

import asyncio

import pytest

import spatial_ui_agent_server.service as service_module
from spatial_ui_agent_server.db import now
from spatial_ui_agent_server.service import SpatialService


@pytest.mark.asyncio
async def test_successful_turn_queues_surface_then_speech(settings, monkeypatch) -> None:
    monkeypatch.setattr(service_module, "GENERATION_HEARTBEAT_SECONDS", 0.01)
    service = SpatialService(settings)
    service.initialize()
    audio = service.upload_dir / "fixture.wav"
    audio.write_bytes(b"unused")
    turn_id = "ae7b1f99-0d49-44b7-a274-9667499e7a33"
    service.store.create_turn(
        {
            "id": turn_id,
            "event_id": "75ada165-67bc-40c2-b07a-262230b4301a",
            "device_id": "rokid-1",
            "audio_path": str(audio),
            "image_path": None,
            "context": {},
            "created_at": now(),
        }
    )

    async def transcribe(*_args) -> str:
        return "Build a yaw game"

    async def generate(*_args, **_kwargs):
        callback = _kwargs.get("on_checking") or _args[3]
        await asyncio.sleep(0.03)
        await callback()
        return {
            "manifest": service.active_surface()["manifest"],
            "summary": "Your yaw game is ready.",
        }

    service.worker.transcribe = transcribe  # type: ignore[method-assign]
    service.generate_surface = generate  # type: ignore[method-assign]
    await service.process_turn(turn_id)

    events = service.store.events_after("rokid-1", 0)
    assert any(event["payload"].get("heartbeat") for event in events)
    assert [event["kind"] for event in events[-3:]] == [
        "surface.available",
        "device.command",
        "turn.status",
    ]
    assert events[-2]["payload"] == {
        "command": "speak",
        "text": "Your yaw game is ready.",
    }
    assert events[-1]["payload"]["status"] == "ready"
    assert service.store.one("SELECT status FROM turns WHERE id=?", (turn_id,))["status"] == "ready"
