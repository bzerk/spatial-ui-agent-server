from __future__ import annotations

import hmac
from pathlib import Path

from starlette.responses import JSONResponse


def read_token(path: Path) -> str | None:
    try:
        token = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return token or None


def bearer_value(headers: dict[str, str] | object) -> str | None:
    authorization = headers.get("authorization", "")  # type: ignore[union-attr]
    scheme, _, value = authorization.partition(" ")
    return value if scheme.lower() == "bearer" and value else None


def token_matches(candidate: str | None, expected: str | None) -> bool:
    return bool(candidate and expected and hmac.compare_digest(candidate, expected))


class BearerGate:
    def __init__(self, app: object, token_file: Path, allowlist: tuple[str, ...] = ()) -> None:
        self.app = app
        self.token_file = token_file
        self.allowlist = allowlist

    async def __call__(self, scope: dict, receive: object, send: object) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)  # type: ignore[operator]
            return
        client = (scope.get("client") or ("", 0))[0]
        headers = {key.decode().lower(): value.decode() for key, value in scope.get("headers", [])}
        if self.allowlist and client not in self.allowlist:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 4403})  # type: ignore[operator]
                return
            response = JSONResponse({"error": "source_not_allowed"}, status_code=403)
            await response(scope, receive, send)
            return
        if not token_matches(bearer_value(headers), read_token(self.token_file)):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 4401})  # type: ignore[operator]
                return
            response = JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)  # type: ignore[operator]
