from __future__ import annotations

import io
import json
import re
import wave

from starlette.testclient import TestClient

from spatial_ui_agent_server.api import create_app
from spatial_ui_agent_server.service import SpatialService


def wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 160)
    return output.getvalue()


def test_health_auth_turn_idempotency_and_websocket(settings) -> None:
    service = SpatialService(settings)

    async def hold_turn(_: str) -> None:
        return None

    service.process_turn = hold_turn  # type: ignore[method-assign]
    app = create_app(settings, service)
    headers = {"Authorization": "Bearer device-secret"}
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["transcriber"]["status"] == "degraded"
        assert client.get("/v1/turns/nope").status_code == 401
        event_id = "9e87688f-4301-4142-8d2d-25b11a6416e8"
        form = {
            "event_id": event_id,
            "device_id": "rokid-1",
            "context": '{"active_surface_revision":"fixture","capabilities":{"orientation":true}}',
        }
        files = {"audio": ("turn.wav", wav_bytes(), "audio/wav")}
        created = client.post("/v1/turns", data=form, files=files, headers=headers)
        duplicate = client.post("/v1/turns", data=form, files=files, headers=headers)
        assert created.status_code == 202
        assert duplicate.status_code == 202
        assert created.json()["schema"] == "spatial.turn.v1"
        assert duplicate.json()["turn_id"] == created.json()["turn_id"]

        event = service.queue_device_event(
            "rokid-1", "device.command", {"command": "speak", "text": "hello"}, "speak-1"
        )
        with client.websocket_connect(
            "/v1/devices/rokid-1/events?cursor=0", headers=headers
        ) as websocket:
            message = websocket.receive_json()
            assert message["schema"] == "spatial.event.v1"
            assert message["sequence"] == event["seq"]
            assert message["event_id"] == event["event_id"]
            websocket.send_json(
                {
                    "schema": "spatial.ack.v1",
                    "event_id": event["event_id"],
                    "device_id": "rokid-1",
                    "state": "rendered",
                    "revision": "abc",
                }
            )
            websocket.send_json({"type": "ping"})
            assert websocket.receive_json()["type"] == "pong"

            active = service.active_surface()
            websocket.send_json(
                {
                    "schema": "spatial.runtime.snapshot.v1",
                    "source_kind": "downloaded",
                    "url": "https://appassets.androidplatform.net/surface/test/index.html",
                    "revision": active["revision"],
                }
            )
            accepted = websocket.receive_json()
            assert accepted == {
                "schema": "spatial.runtime.snapshot.accepted.v1",
                "revision": active["revision"],
            }
        ack = service.store.one(
            "SELECT * FROM acknowledgements WHERE event_id=?", (event["event_id"],)
        )
        assert ack and ack["status"] == "rendered" and ack["revision"] == "abc"
        assert service.device_surface("rokid-1")["revision"] == active["revision"]


def test_surface_download_requires_device_auth(settings) -> None:
    service = SpatialService(settings)
    app = create_app(settings, service)
    with TestClient(app) as client:
        active = service.active_surface()
        path = f"/v1/surfaces/{active['revision']}.zip"
        assert client.get(path).status_code == 401
        response = client.get(path, headers={"Authorization": "Bearer device-secret"})
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"


def test_loopback_admin_console_state_logs_and_actions(settings) -> None:
    with TestClient(create_app(settings, SpatialService(settings))) as remote_client:
        assert remote_client.get("/admin").status_code == 403

    service = SpatialService(settings)
    app = create_app(settings, service)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        page = client.get("/admin")
        assert page.status_code == 200
        assert "Command deck" in page.text
        assert client.get("/favicon.ico").status_code == 204
        token_match = re.search(r"const csrfToken = (\"[^\"]+\");", page.text)
        assert token_match
        csrf_token = json.loads(token_match.group(1))

        state = client.get("/admin/state")
        assert state.status_code == 200
        assert state.json()["active_surface"]
        assert state.json()["log_file"] == str(settings.log_file)
        assert client.get("/admin/logs").text == "Log file has not been created yet."

        action = {"action": "push-active", "device_id": "rokid-console-test"}
        assert client.post("/admin/actions", json=action).status_code == 403
        queued = client.post("/admin/actions", json=action, headers={"X-CSRF-Token": csrf_token})
        assert queued.status_code == 200
        assert queued.json()["event"]["device_id"] == "rokid-console-test"

        speech = client.post(
            "/admin/actions",
            json={"action": "speak", "device_id": "rokid-console-test", "text": "ready"},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert speech.status_code == 200
        assert speech.json()["event"]["payload"]["command"] == "speak"
