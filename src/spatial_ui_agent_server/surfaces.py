from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .guidelines import surface_guidelines_metadata

MAX_FILES = 127
MAX_BYTES = 8 * 1024 * 1024
VIEWPORT = {
    "androidPixels": [480, 640],
    "cssPixels": [320, 427],
    "devicePixelRatio": 1.5,
    "safeInsets": [40, 34, 40, 34],
    "safeInsetsCss": [27, 23, 27, 23],
    "preferredContentPixels": [400, 572],
    "preferredContentCssPixels": [266, 381],
}
TEXT_EXTENSIONS = {".html", ".css", ".js", ".json", ".svg", ".txt"}


class SurfaceValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class SurfacePackage:
    revision: str
    manifest: dict[str, Any]
    zip_path: Path


def _safe_relative(path: str) -> bool:
    value = PurePosixPath(path)
    return bool(path and not value.is_absolute() and ".." not in value.parts and "\\" not in path)


def _text_files(root: Path) -> list[tuple[Path, str]]:
    result: list[tuple[Path, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise SurfaceValidationError([f"symlinks are forbidden: {path.name}"])
        if path.is_file() and path.name != "surface.json":
            result.append((path, path.relative_to(root).as_posix()))
    return result


def validate_surface(root: Path) -> list[str]:
    errors: list[str] = []
    files = _text_files(root)
    if not files:
        errors.append("surface has no files")
    if len(files) > MAX_FILES:
        errors.append(
            f"surface has {len(files)} content files; maximum is {MAX_FILES} "
            "(128 including surface.json)"
        )
    total = sum(path.stat().st_size for path, _ in files)
    if total > MAX_BYTES:
        errors.append(f"surface is {total} bytes; maximum is {MAX_BYTES}")
    names = {relative for _, relative in files}
    if "index.html" not in names:
        errors.append("index.html is required")

    combined = ""
    for path, relative in files:
        if not _safe_relative(relative):
            errors.append(f"unsafe path: {relative}")
        if path.suffix.lower() in TEXT_EXTENSIONS:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                errors.append(f"text file is not UTF-8: {relative}")
                continue
            combined += f"\n/* {relative} */\n{text}"

    lowered = combined.lower()
    viewport_tags = [
        tag
        for tag in re.findall(r"<meta\b[^>]*>", lowered)
        if re.search(r"\bname\s*=\s*(['\"])viewport\1", tag)
    ]
    if not any(re.search(r"\bwidth\s*=\s*device-width\b", tag) for tag in viewport_tags):
        errors.append("viewport meta must use width=device-width for the 320x427 CSS viewport")
    if re.search(r"(?:linear|radial|conic)-gradient\s*\(", lowered):
        errors.append("gradients are forbidden")
    if re.search(
        r"(?:background|background-color)\s*:\s*(?!#000(?:000)?\b|black\b)(?:#0[0-9a-f]{2,5}\b|rgb\(\s*([0-9]|1[0-5])\s*,)",
        lowered,
    ):
        errors.append("near-black backgrounds are forbidden; use transparent optical black")
    if re.search(r"(?:background|background-color)\s*:\s*(?:#000(?:000)?\b|black\b)", lowered):
        errors.append("opaque black CSS backgrounds are forbidden; use transparent optical black")
    if re.search(r"\.fillstyle\s*=\s*['\"](?:#000(?:000)?|black)['\"]", lowered):
        errors.append("opaque black canvas fills are forbidden; clear to transparency")
    if re.search(
        r"\.clearcolor\(\s*0(?:\.0+)?\s*,\s*0(?:\.0+)?\s*,\s*0(?:\.0+)?\s*,\s*1(?:\.0+)?\s*\)",
        lowered,
    ):
        errors.append("opaque WebGL black clears are forbidden; clear with alpha zero")
    if re.search(r"(?:width\s*:\s*100vw|inset\s*:\s*0)[^}]{0,180}(?:rgba?|hsla?)\(", lowered):
        errors.append("full-screen tinted layers are forbidden")
    if any(term in lowered for term in ("material-icons", "bottom-nav", "tab-bar", "phone-frame")):
        errors.append("phone-style layout primitives are forbidden")
    for axis, limit in (("width", 320), ("height", 427), ("left", 320), ("top", 427)):
        for match in re.finditer(rf"\b{axis}\s*:\s*(\d+)px", lowered):
            if int(match.group(1)) > limit:
                errors.append(f"{axis} exceeds viewport: {match.group(0)}")
    if re.search(
        r"(?:src|href)\s*=\s*['\"]\s*(?:https?:)?//|url\(\s*['\"]?(?:https?:)?//|"
        r"\bimport\s*(?:\(|[^;]*?from\s*)['\"](?:https?:)?//",
        lowered,
    ):
        errors.append(
            "remote resources are forbidden by the current surface contract; "
            "see docs/NETWORK_CAPABILITIES.md"
        )
    if re.search(r"\b(?:eval|new\s+function)\s*\(", lowered):
        errors.append("dynamic JavaScript evaluation is forbidden")
    if (
        "<html" not in lowered
        or "<script" not in lowered
        or ("<style" not in lowered and ".css" not in lowered)
    ):
        errors.append("surface must contain HTML, CSS, and JavaScript")
    if errors:
        raise SurfaceValidationError(sorted(set(errors)))
    return [relative for _, relative in files]


def package_surface(source: Path, destination: Path, source_name: str) -> SurfacePackage:
    files = validate_surface(source)
    file_map = {
        relative: hashlib.sha256((source / relative).read_bytes()).hexdigest() for relative in files
    }
    contract = {
        "schema": "spatial.surface.v1",
        "entrypoint": "index.html",
        "files": file_map,
        "backgroundMode": "transparent-ar",
        "capabilities": {
            "webgl": True,
            "webxr": "inline-3dof",
            "orientation": True,
            "pointer": True,
            "cameraStill": True,
            "cameraStream": "best-effort",
        },
        "designGuidelines": surface_guidelines_metadata(),
        "viewport": VIEWPORT,
    }
    canonical = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    revision = hashlib.sha256(canonical).hexdigest()
    manifest = contract | {"revision": revision}
    destination.mkdir(parents=True, exist_ok=True)
    zip_path = destination / f"{revision}.zip"
    if zip_path.exists():
        return SurfacePackage(revision, manifest, zip_path)
    with tempfile.TemporaryDirectory(dir=destination) as temporary:
        staging = Path(temporary)
        for relative in files:
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, target)
        (staging / "surface.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(staging).as_posix())
    return SurfacePackage(revision, manifest, zip_path)


def materialize_generated(files: list[dict[str, str]], root: Path) -> None:
    for item in files:
        relative = item.get("path", "")
        content = item.get("content", "")
        if not _safe_relative(relative):
            raise SurfaceValidationError([f"unsafe generated path: {relative}"])
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
