#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import math
import struct
import time
import uuid
import wave

import httpx

from spatial_ui_agent_server.auth import read_token
from spatial_ui_agent_server.config import Settings


def audio_fixture() -> bytes:
    output = io.BytesIO()
    samples = [int(1800 * math.sin(2 * math.pi * 220 * index / 16000)) for index in range(8000)]
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return output.getvalue()


def main() -> None:
    settings = Settings.from_env()
    token = read_token(settings.device_token_file)
    if not token:
        raise SystemExit("generate the local device token before smoke testing")
    headers = {"Authorization": f"Bearer {token}"}
    base_url = f"http://127.0.0.1:{settings.port}"
    with httpx.Client(base_url=base_url, headers=headers, timeout=30) as client:
        response = client.post(
            "/v1/turns",
            data={
                "device_id": "laptop-smoke",
                "event_id": str(uuid.uuid4()),
                "context": json.dumps({"capabilities": {"orientation": True}}),
            },
            files={"audio": ("smoke.wav", audio_fixture(), "audio/wav")},
        )
        response.raise_for_status()
        turn = response.json()
        deadline = time.monotonic() + settings.codex_timeout_seconds + 150
        while time.monotonic() < deadline:
            status = client.get(f"/v1/turns/{turn['turn_id']}")
            status.raise_for_status()
            result = status.json()
            if result["status"] in {"ready", "failed"}:
                print(
                    json.dumps(
                        {
                            "schema": result["schema"],
                            "status": result["status"],
                            "surfaceRevision": result["surface_revision"],
                            "error": result["error"],
                        }
                    )
                )
                if result["status"] != "ready":
                    raise SystemExit(1)
                return
            time.sleep(2)
    raise SystemExit("turn did not reach a terminal state before the smoke timeout")


if __name__ == "__main__":
    main()
