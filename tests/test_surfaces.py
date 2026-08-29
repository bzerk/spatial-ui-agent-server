from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from spatial_ui_agent_server.surfaces import (
    SurfaceValidationError,
    package_surface,
    validate_surface,
)


def valid_surface(root: Path) -> None:
    (root / "index.html").write_text(
        '<html><meta name="viewport" content="width=device-width,initial-scale=1">'
        "<style>html,body{background:transparent}</style><body>"
        "<script>let yaw=0;</script></body></html>",
        encoding="utf-8",
    )


def test_package_is_immutable_and_self_describing(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    valid_surface(source)
    first = package_surface(source, tmp_path / "bundles", "test")
    second = package_surface(source, tmp_path / "bundles", "test")
    assert first.revision == second.revision
    with zipfile.ZipFile(first.zip_path) as archive:
        manifest = json.loads(archive.read("surface.json"))
    assert manifest["schema"] == "spatial.surface.v1"
    assert manifest["revision"] == first.revision
    assert manifest["viewport"]["androidPixels"] == [480, 640]
    assert manifest["viewport"]["cssPixels"] == [320, 427]
    assert manifest["viewport"]["devicePixelRatio"] == 1.5
    assert manifest["backgroundMode"] == "transparent-ar"
    assert len(manifest["files"]["index.html"]) == 64


@pytest.mark.parametrize(
    "css,error",
    [
        ("background:linear-gradient(#000,#111)", "gradients"),
        ("background:#080808", "near-black"),
        ("background:#000000", "transparent optical black"),
        ("width:481px", "exceeds viewport"),
    ],
)
def test_validator_rejects_rokid_violations(tmp_path: Path, css: str, error: str) -> None:
    (tmp_path / "index.html").write_text(
        f"<html><style>body{{{css}}}</style><script>let x=1;</script></html>", encoding="utf-8"
    )
    with pytest.raises(SurfaceValidationError, match=error):
        validate_surface(tmp_path)


def test_javascript_comments_do_not_look_like_remote_resources(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(
        '<html><meta name="viewport" content="width=device-width">'
        "<style>body{background:transparent}</style><body>"
        "<script>// local-only comment\nlet yaw=0;</script></body></html>",
        encoding="utf-8",
    )

    assert validate_surface(tmp_path) == ["index.html"]


def test_fixed_physical_viewport_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(
        '<html><meta name="viewport" content="width=480,height=640">'
        "<style>body{background:transparent}</style><script>let x=1;</script></html>",
        encoding="utf-8",
    )

    with pytest.raises(SurfaceValidationError, match="320x427 CSS viewport"):
        validate_surface(tmp_path)


def test_remote_resources_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(
        '<html><style>body{background:transparent}</style><script src="https://example.test/a.js"></script></html>',
        encoding="utf-8",
    )

    with pytest.raises(SurfaceValidationError, match="remote resources"):
        validate_surface(tmp_path)
