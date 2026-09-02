from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .config import Settings
from .guidelines import surface_guidelines_document
from .surfaces import SurfaceValidationError, materialize_generated, validate_surface

OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "files"],
    "properties": {
        "summary": {"type": "string", "minLength": 1, "maxLength": 180},
        "files": {
            "type": "array",
            "minItems": 1,
            "maxItems": 127,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["path", "content"],
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            },
        },
    },
}


class CodexGenerator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def generate(
        self,
        request: str,
        current_source: str,
        output_dir: Path,
        image_path: Path | None = None,
        on_checking: Callable[[], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        errors: list[str] = []
        for attempt in range(2):
            prompt = self._prompt(request, current_source, errors if attempt else [])
            result = await self._run(prompt, image_path)
            if on_checking:
                await on_checking()
            with tempfile.TemporaryDirectory(dir=output_dir.parent) as temporary:
                candidate = Path(temporary)
                materialize_generated(result["files"], candidate)
                try:
                    validate_surface(candidate)
                except SurfaceValidationError as error:
                    errors = error.errors
                    if attempt == 0:
                        continue
                    raise
                output_dir.mkdir(parents=True, exist_ok=False)
                for path in candidate.rglob("*"):
                    if path.is_file():
                        target = output_dir / path.relative_to(candidate)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(path.read_bytes())
                return result
        raise RuntimeError("generator exhausted bounded repair pass")

    def _prompt(self, request: str, current_source: str, errors: list[str]) -> str:
        repair = "\nValidator errors to repair exactly:\n- " + "\n- ".join(errors) if errors else ""
        guidelines = surface_guidelines_document()
        return f"""Create a complete local HTML/CSS/JS Rokid spatial surface for: {request}

Follow the complete Rokid UI guide below. It is authoritative over generic web, mobile, and
desktop design conventions. Guide ID {guidelines["id"]}, version {guidelines["version"]}, SHA-256
{guidelines["sha256"]}.

--- BEGIN ROKID UI GUIDELINES ---
{guidelines["text"]}
--- END ROKID UI GUIDELINES ---

Return only the output matching the supplied JSON schema. Each file must be UTF-8 text.
Summary must be one short, speech-friendly sentence of at most 160 characters describing the
result. Do not put code, markup, URLs, filenames, controls, or display-only details in summary.

Current active source, provided only as continuity context:
---
{current_source[:20000]}
---{repair}"""

    async def _run(self, prompt: str, image_path: Path | None) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            schema = root / "schema.json"
            output = root / "output.json"
            schema.write_text(json.dumps(OUTPUT_SCHEMA), encoding="utf-8")
            command = [
                self.settings.codex_bin,
                "exec",
                "--ephemeral",
                "--model",
                self.settings.codex_model,
                "--sandbox",
                "workspace-write",
                "--config",
                f'model_reasoning_effort="{self.settings.codex_reasoning}"',
                "--output-schema",
                str(schema),
                "--output-last-message",
                str(output),
                "--skip-git-repo-check",
            ]
            if image_path:
                command.extend(["--image", str(image_path)])
            command.append("-")
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                cwd=root,
                start_new_session=True,
            )
            try:
                _, stderr = await asyncio.wait_for(
                    process.communicate(prompt.encode()),
                    timeout=self.settings.codex_timeout_seconds,
                )
            except TimeoutError as error:
                await self._terminate(process)
                raise RuntimeError(
                    f"Codex generator timed out after {self.settings.codex_timeout_seconds} seconds"
                ) from error
            except asyncio.CancelledError:
                await self._terminate(process)
                raise
            if process.returncode:
                raise RuntimeError(f"Codex generator failed: {stderr.decode()[-2000:]}")
            return json.loads(output.read_text(encoding="utf-8"))

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=3)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()


def read_surface_source(zip_path: Path) -> str:
    import zipfile

    chunks: list[str] = []
    with zipfile.ZipFile(zip_path) as archive:
        for name in sorted(archive.namelist()):
            if Path(name).suffix.lower() in {".html", ".css", ".js"}:
                chunks.append(f"\n/* {name} */\n{archive.read(name).decode('utf-8')}")
    return "".join(chunks)
