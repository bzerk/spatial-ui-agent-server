from __future__ import annotations

import asyncio
import json
import logging
import shutil
import struct
import uuid
import wave
from pathlib import Path

from .config import Settings

LOGGER = logging.getLogger(__name__)


class TranscriberUnavailable(RuntimeError):
    pass


def wav_to_f32_16khz(source: Path, destination: Path) -> None:
    with wave.open(str(source), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if channels not in {1, 2} or width not in {1, 2, 4} or rate <= 0:
        raise ValueError("WAV must be mono/stereo PCM with 8, 16, or 32-bit samples")
    scale = float(1 << (width * 8 - 1))
    samples: list[float] = []
    frame_size = width * channels
    for offset in range(0, len(frames) - frame_size + 1, frame_size):
        values = []
        for channel in range(channels):
            raw = frames[offset + channel * width : offset + (channel + 1) * width]
            if width == 1:
                values.append((raw[0] - 128) / 128.0)
            else:
                values.append(int.from_bytes(raw, "little", signed=True) / scale)
        samples.append(sum(values) / channels)
    if not samples:
        raise ValueError("WAV contains no audio frames")
    if rate != 16000:
        output_length = max(1, round(len(samples) * 16000 / rate))
        resampled: list[float] = []
        for index in range(output_length):
            position = index * rate / 16000
            left = min(int(position), len(samples) - 1)
            right = min(left + 1, len(samples) - 1)
            fraction = position - left
            resampled.append(samples[left] * (1 - fraction) + samples[right] * fraction)
        samples = resampled
    destination.write_bytes(struct.pack(f"<{len(samples)}f", *samples))


class WhisperWorker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.process: asyncio.subprocess.Process | None = None
        self.lock = asyncio.Lock()
        self.ready: dict | None = None
        self.last_error: str | None = None

    def executable(self) -> Path:
        if self.settings.transcriber_bin.is_file():
            return self.settings.transcriber_bin
        discovered = shutil.which(str(self.settings.transcriber_bin))
        if discovered:
            return Path(discovered)
        fallback = self.settings.transcriber_fallback_bin
        if fallback and fallback.is_file():
            return fallback
        raise TranscriberUnavailable(
            f"transcriber missing at {self.settings.transcriber_bin} and configured fallback"
        )

    async def start(self) -> None:
        if self.process and self.process.returncode is None:
            return
        if not self.settings.whisper_model.is_file():
            raise TranscriberUnavailable(f"Whisper model missing: {self.settings.whisper_model}")
        executable = self.executable()
        self.process = await asyncio.create_subprocess_exec(
            str(executable),
            str(self.settings.whisper_model),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert self.process.stdout
        try:
            line = await asyncio.wait_for(self.process.stdout.readline(), timeout=30)
            self.ready = json.loads(line)
            if self.ready.get("kind") != "ready":
                raise ValueError("worker did not send ready frame")
            self.last_error = None
        except Exception as error:
            self.last_error = str(error)
            await self.stop()
            raise TranscriberUnavailable(f"failed to prewarm Whisper worker: {error}") from error

    async def stop(self) -> None:
        if not self.process:
            return
        if self.process.stdin:
            self.process.stdin.close()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=3)
        except TimeoutError:
            self.process.kill()
            await self.process.wait()
        self.process = None
        self.ready = None

    async def transcribe(self, wav_path: Path, scratch_dir: Path) -> str:
        scratch_dir.mkdir(parents=True, exist_ok=True)
        request_id = str(uuid.uuid4())
        raw_path = scratch_dir / f"{request_id}.f32"
        await asyncio.to_thread(wav_to_f32_16khz, wav_path, raw_path)
        try:
            async with self.lock:
                await self.start()
                assert self.process and self.process.stdin and self.process.stdout
                frame = {"id": request_id, "audio_path": str(raw_path), "language": "en"}
                self.process.stdin.write((json.dumps(frame) + "\n").encode())
                await self.process.stdin.drain()
                line = await asyncio.wait_for(self.process.stdout.readline(), timeout=120)
                if not line:
                    raise TranscriberUnavailable("Whisper worker exited without a response")
                result = json.loads(line)
                if result.get("id") != request_id or not result.get("ok"):
                    raise RuntimeError(result.get("error") or "invalid Whisper response")
                return str(result.get("text", "")).strip()
        except Exception as error:
            self.last_error = str(error)
            if self.process and self.process.returncode is not None:
                self.process = None
            if self.settings.transcriber_fallback in {"empty", "fixture"}:
                LOGGER.warning(
                    "transcriber failed; returning configured degraded fallback: %s", error
                )
                return "" if self.settings.transcriber_fallback == "empty" else "Fixture voice turn"
            raise
        finally:
            raw_path.unlink(missing_ok=True)

    def health(self) -> dict:
        running = bool(self.process and self.process.returncode is None and self.ready)
        available = self._has_executable() and self.settings.whisper_model.is_file()
        return {
            "status": "ready" if running else ("not_started" if available else "degraded"),
            "configuredBinary": self.settings.transcriber_bin.name,
            "resolvedBinary": self.executable().name if self._has_executable() else None,
            "model": self.settings.whisper_model.name,
            "modelAvailable": self.settings.whisper_model.is_file(),
            "lastError": self.last_error,
            "fallbackMode": self.settings.transcriber_fallback,
        }

    def _has_executable(self) -> bool:
        try:
            self.executable()
        except TranscriberUnavailable:
            return False
        return True
