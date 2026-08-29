from __future__ import annotations

import asyncio
import json
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from .config import Settings
from .db import Store
from .generator import CodexGenerator, read_surface_source
from .surfaces import SurfacePackage, materialize_generated, package_surface
from .transcriber import WhisperWorker

GENERATION_HEARTBEAT_SECONDS = 15.0


class SpatialService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = Store(settings.data_dir / "spatial.db")
        self.worker = WhisperWorker(settings)
        self.generator = CodexGenerator(settings)
        self.surface_dir = settings.data_dir / "surfaces"
        self.upload_dir = settings.data_dir / "uploads"
        self.scratch_dir = settings.data_dir / "scratch"

    def initialize(self) -> None:
        for directory in (self.surface_dir, self.upload_dir, self.scratch_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.store.initialize()
        if not self.store.active_surface():
            self.install_fixture("constellation", activate=True)
        self.install_fixture("brick-breaker", activate=False)

    def install_fixture(self, name: str, activate: bool) -> SurfacePackage:
        root = Path(__file__).parent / "fixtures" / name
        package = package_surface(root, self.surface_dir, f"fixture:{name}")
        if not self.store.one(
            "SELECT revision FROM surfaces WHERE revision=?", (package.revision,)
        ):
            self.store.put_surface(
                package.revision, package.manifest, package.zip_path, f"fixture:{name}"
            )
        if activate:
            self.store.set_active(package.revision)
        return package

    def surface(self, revision: str) -> dict[str, Any] | None:
        row = self.store.one("SELECT * FROM surfaces WHERE revision=?", (revision,))
        if row:
            row["manifest"] = json.loads(row.pop("manifest_json"))
        return row

    def active_surface(self) -> dict[str, Any]:
        row = self.store.active_surface()
        if not row:
            raise RuntimeError("no active surface")
        row["manifest"] = json.loads(row.pop("manifest_json"))
        return row

    async def generate_surface(
        self,
        request: str,
        image_path: Path | None = None,
        context: dict[str, Any] | None = None,
        on_checking: Any = None,
    ) -> dict[str, Any]:
        active = self.active_surface()
        source = read_surface_source(Path(active["zip_path"]))
        candidate = self.scratch_dir / f"generated-{uuid.uuid4()}"
        context_note = (
            f"\nDevice context: {json.dumps(context, separators=(',', ':'))[:4000]}"
            if context
            else ""
        )
        generated = await self.generator.generate(
            request + context_note, source, candidate, image_path, on_checking=on_checking
        )
        package = package_surface(candidate, self.surface_dir, "codex")
        if not self.store.one(
            "SELECT revision FROM surfaces WHERE revision=?", (package.revision,)
        ):
            self.store.put_surface(package.revision, package.manifest, package.zip_path, "codex")
        self.store.set_active(package.revision)
        return {
            "manifest": package.manifest,
            "summary": self.speech_summary(generated.get("summary")),
        }

    def put_surface(self, files: list[dict[str, str]], source: str = "mcp") -> dict[str, Any]:
        with tempfile.TemporaryDirectory(dir=self.scratch_dir) as temporary:
            root = Path(temporary)
            materialize_generated(files, root)
            package = package_surface(root, self.surface_dir, source)
        if not self.store.one(
            "SELECT revision FROM surfaces WHERE revision=?", (package.revision,)
        ):
            self.store.put_surface(package.revision, package.manifest, package.zip_path, source)
        return package.manifest

    def push_surface(
        self, device_id: str, revision: str, turn_id: str | None = None
    ) -> dict[str, Any]:
        if not self.surface(revision):
            raise ValueError("unknown surface revision")
        return self.queue_device_event(
            device_id,
            "surface.available",
            {
                "revision": revision,
                "bundle_url": f"/v1/surfaces/{revision}.zip",
                "turn_id": turn_id,
            },
            f"surface:{revision}:{turn_id}" if turn_id else None,
        )

    def queue_device_event(
        self, device_id: str, kind: str, payload: dict[str, Any], idempotency_key: str | None = None
    ) -> dict[str, Any]:
        return self.store.append_event(
            str(uuid.uuid4()), device_id, kind, payload, idempotency_key or str(uuid.uuid4())
        )

    async def process_turn(self, turn_id: str) -> None:
        turn = self.store.one("SELECT * FROM turns WHERE id=?", (turn_id,))
        if not turn:
            return
        try:
            self.store.update_turn(turn_id, status="transcribing")
            self.turn_status(turn, "transcribing")
            transcript = await self.worker.transcribe(Path(turn["audio_path"]), self.scratch_dir)
            self.store.update_turn(turn_id, status="designing", transcript=transcript)
            self.turn_status(turn, "designing")
            image = Path(turn["image_path"]) if turn.get("image_path") else None
            context = json.loads(turn.get("context_json") or "{}")
            phase = "designing"

            async def checking() -> None:
                nonlocal phase
                phase = "checking"
                self.store.update_turn(turn_id, status="checking")
                self.turn_status(turn, "checking")

            generation = asyncio.create_task(
                self.generate_surface(
                    transcript or "Show the default constellation", image, context, checking
                )
            )
            try:
                while True:
                    try:
                        generated = await asyncio.wait_for(
                            asyncio.shield(generation), timeout=GENERATION_HEARTBEAT_SECONDS
                        )
                        break
                    except TimeoutError:
                        self.store.update_turn(turn_id, status=phase)
                        slot = int(time.monotonic() // GENERATION_HEARTBEAT_SECONDS)
                        self.queue_device_event(
                            turn["device_id"],
                            "turn.status",
                            {"turn_id": turn_id, "status": phase, "heartbeat": True},
                            f"turn:{turn_id}:{phase}:heartbeat:{slot}",
                        )
            finally:
                if not generation.done():
                    generation.cancel()
                    await asyncio.gather(generation, return_exceptions=True)
            manifest = generated["manifest"]
            self.store.update_turn(turn_id, status="pushing")
            self.turn_status(turn, "pushing")
            self.push_surface(turn["device_id"], manifest["revision"], turn_id)
            self.queue_device_event(
                turn["device_id"],
                "device.command",
                {"command": "speak", "text": generated["summary"]},
                f"turn:{turn_id}:speak",
            )
            self.store.update_turn(turn_id, status="ready", surface_revision=manifest["revision"])
            self.turn_status(turn, "ready")
        except Exception as error:
            self.store.update_turn(turn_id, status="failed", error=str(error)[:2000])
            self.turn_status(turn, "failed", str(error)[:500])

    def turn_status(
        self, turn: dict[str, Any], status: str, error: str | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"turn_id": turn["id"], "status": status}
        if error:
            payload["error"] = error
        return self.queue_device_event(
            turn["device_id"], "turn.status", payload, f"turn:{turn['id']}:{status}"
        )

    @staticmethod
    def speech_summary(value: Any) -> str:
        summary = " ".join(str(value or "").split())[:160].strip()
        unsafe = ("`", "<", ">", "{", "}", "http://", "https://", "function(", "=>")
        if not summary or any(marker in summary.lower() for marker in unsafe):
            return "Your spatial surface is ready."
        return summary
