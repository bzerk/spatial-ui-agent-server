from __future__ import annotations

from pathlib import Path

from spatial_ui_agent_server.generator import CodexGenerator
from spatial_ui_agent_server.guidelines import (
    surface_guidelines_document,
    surface_guidelines_text,
)


def test_repository_document_is_the_runtime_source() -> None:
    repository_document = (
        Path(__file__).resolve().parents[1] / "docs" / "ROKID_UI_GUIDELINES.md"
    ).read_text(encoding="utf-8")
    guidelines = surface_guidelines_document()

    assert surface_guidelines_text() == repository_document
    assert guidelines["id"] == "rokid.ui.webxr.v1"
    assert guidelines["version"] == "2026-09-02"
    assert len(guidelines["sha256"]) == 64
    assert guidelines["media_type"] == "text/markdown"


def test_generator_injects_the_complete_canonical_document(settings) -> None:
    guidelines = surface_guidelines_document()
    prompt = CodexGenerator(settings)._prompt("Make a reader", "<html></html>", [])

    assert guidelines["text"] in prompt
    assert guidelines["sha256"] in prompt
    assert "authoritative over generic web, mobile" in prompt
    assert "desktop design conventions" in prompt
