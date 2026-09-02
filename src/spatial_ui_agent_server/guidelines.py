from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

GUIDELINES_FILENAME = "ROKID_UI_GUIDELINES.md"
GUIDELINES_RESOURCE = "resources"
_ID_PATTERN = re.compile(r"^Guidelines ID: `([^`]+)`$", re.MULTILINE)
_VERSION_PATTERN = re.compile(r"^Guidelines version: `([^`]+)`$", re.MULTILINE)


@lru_cache(maxsize=1)
def surface_guidelines_text() -> str:
    packaged = resources.files("spatial_ui_agent_server").joinpath(
        GUIDELINES_RESOURCE, GUIDELINES_FILENAME
    )
    try:
        return packaged.read_text(encoding="utf-8")
    except FileNotFoundError:
        repository_copy = Path(__file__).resolve().parents[2] / "docs" / GUIDELINES_FILENAME
        return repository_copy.read_text(encoding="utf-8")


def _required_match(pattern: re.Pattern[str], text: str, field: str) -> str:
    match = pattern.search(text)
    if not match:
        raise RuntimeError(f"Rokid UI guidelines are missing {field}")
    return match.group(1)


def surface_guidelines_metadata() -> dict[str, str]:
    text = surface_guidelines_text()
    return {
        "id": _required_match(_ID_PATTERN, text, "an ID"),
        "version": _required_match(_VERSION_PATTERN, text, "a version"),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def surface_guidelines_document() -> dict[str, Any]:
    return {
        **surface_guidelines_metadata(),
        "media_type": "text/markdown",
        "text": surface_guidelines_text(),
    }
