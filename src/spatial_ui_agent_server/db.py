from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, device_id TEXT NOT NULL,
                    status TEXT NOT NULL, audio_path TEXT NOT NULL, image_path TEXT,
                    context_json TEXT NOT NULL DEFAULT '{}',
                    transcript TEXT, surface_revision TEXT, error TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS surfaces (
                    revision TEXT PRIMARY KEY, manifest_json TEXT NOT NULL, zip_path TEXT NOT NULL,
                    source TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY,
                    last_seen TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS device_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
                    device_id TEXT NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(device_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS acknowledgements (
                    event_id TEXT NOT NULL, device_id TEXT NOT NULL, status TEXT NOT NULL,
                    revision TEXT, detail TEXT, created_at TEXT NOT NULL,
                    PRIMARY KEY(event_id, device_id, status),
                    FOREIGN KEY(event_id) REFERENCES device_events(event_id)
                );
                """
            )

    def one(self, query: str, parameters: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(query, parameters).fetchone()
            return dict(row) if row else None

    def all(self, query: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(query, parameters).fetchall()]

    def execute(self, query: str, parameters: tuple[Any, ...] = ()) -> None:
        with self._write_lock, self.connect() as db:
            db.execute(query, parameters)

    def create_turn(self, turn: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        with self._write_lock, self.connect() as db:
            existing = db.execute(
                "SELECT * FROM turns WHERE event_id=?", (turn["event_id"],)
            ).fetchone()
            if existing:
                return dict(existing), False
            db.execute(
                """INSERT INTO turns
                (id,event_id,device_id,status,audio_path,image_path,context_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    turn["id"],
                    turn["event_id"],
                    turn["device_id"],
                    "queued",
                    turn["audio_path"],
                    turn.get("image_path"),
                    json.dumps(turn.get("context", {}), separators=(",", ":")),
                    turn["created_at"],
                    turn["created_at"],
                ),
            )
            return turn | {"status": "queued", "updated_at": turn["created_at"]}, True

    def update_turn(self, turn_id: str, **values: Any) -> None:
        values["updated_at"] = now()
        assignments = ",".join(f"{key}=?" for key in values)
        self.execute(f"UPDATE turns SET {assignments} WHERE id=?", (*values.values(), turn_id))

    def put_surface(
        self, revision: str, manifest: dict[str, Any], zip_path: Path, source: str
    ) -> None:
        self.execute(
            "INSERT INTO surfaces VALUES (?,?,?,?,?)",
            (revision, json.dumps(manifest, separators=(",", ":")), str(zip_path), source, now()),
        )

    def set_active(self, revision: str) -> None:
        self.execute(
            "INSERT INTO state(key,value) VALUES('active_surface',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (revision,),
        )

    def active_surface(self) -> dict[str, Any] | None:
        return self.one(
            "SELECT s.* FROM surfaces s JOIN state st ON st.value=s.revision "
            "WHERE st.key='active_surface'"
        )

    def touch_device(self, device_id: str) -> None:
        self.execute(
            "INSERT INTO devices(id,last_seen) VALUES(?,?) "
            "ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen",
            (device_id, now()),
        )

    def update_device_metadata(self, device_id: str, values: dict[str, Any]) -> dict[str, Any]:
        with self._write_lock, self.connect() as db:
            row = db.execute(
                "SELECT metadata_json FROM devices WHERE id=?", (device_id,)
            ).fetchone()
            metadata = json.loads(row["metadata_json"]) if row else {}
            metadata.update(values)
            timestamp = now()
            db.execute(
                "INSERT INTO devices(id,last_seen,metadata_json) VALUES(?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen, "
                "metadata_json=excluded.metadata_json",
                (device_id, timestamp, json.dumps(metadata, separators=(",", ":"))),
            )
            return {"id": device_id, "last_seen": timestamp, "metadata": metadata}

    def append_event(
        self,
        event_id: str,
        device_id: str,
        kind: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        with self._write_lock, self.connect() as db:
            existing = db.execute(
                "SELECT * FROM device_events WHERE device_id=? AND idempotency_key=?",
                (device_id, idempotency_key),
            ).fetchone()
            if existing:
                return self._decode_event(dict(existing))
            db.execute(
                """INSERT INTO device_events
                (event_id,device_id,kind,payload_json,idempotency_key,created_at)
                VALUES (?,?,?,?,?,?)""",
                (event_id, device_id, kind, json.dumps(payload), idempotency_key, now()),
            )
            row = db.execute("SELECT * FROM device_events WHERE event_id=?", (event_id,)).fetchone()
            return self._decode_event(dict(row))

    def events_after(self, device_id: str, cursor: int) -> list[dict[str, Any]]:
        rows = self.all(
            "SELECT * FROM device_events WHERE device_id=? AND seq>? ORDER BY seq LIMIT 100",
            (device_id, cursor),
        )
        return [self._decode_event(row) for row in rows]

    @staticmethod
    def _decode_event(row: dict[str, Any]) -> dict[str, Any]:
        row["payload"] = json.loads(row.pop("payload_json"))
        return row

    def acknowledge(
        self, device_id: str, event_id: str, status: str, revision: str | None, detail: str | None
    ) -> bool:
        with self._write_lock, self.connect() as db:
            event = db.execute(
                "SELECT 1 FROM device_events WHERE event_id=? AND device_id=?",
                (event_id, device_id),
            ).fetchone()
            if not event:
                return False
            db.execute(
                "INSERT OR IGNORE INTO acknowledgements VALUES (?,?,?,?,?,?)",
                (event_id, device_id, status, revision, detail, now()),
            )
            return True
