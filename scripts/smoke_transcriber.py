#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import math
import struct
import tempfile
import wave
from dataclasses import replace
from pathlib import Path

from spatial_ui_agent_server.config import Settings
from spatial_ui_agent_server.transcriber import WhisperWorker


async def smoke() -> None:
    settings = replace(Settings.from_env(), transcriber_fallback="error")
    worker = WhisperWorker(settings)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        wav_path = root / "smoke.wav"
        samples = [int(1800 * math.sin(2 * math.pi * 220 * index / 16000)) for index in range(8000)]
        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(struct.pack(f"<{len(samples)}h", *samples))
        try:
            await worker.start()
            transcript = await worker.transcribe(wav_path, root)
            print(json.dumps({"worker": "ready", "request": "completed", "text": transcript}))
        finally:
            await worker.stop()


if __name__ == "__main__":
    asyncio.run(smoke())
