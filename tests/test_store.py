from __future__ import annotations

import sqlite3

import pytest

import spatial_ui_agent_server.db as db_module
from spatial_ui_agent_server.db import Store


def test_event_idempotency_replay_and_ack(settings) -> None:
    store = Store(settings.data_dir / "test.db")
    store.initialize()
    first = store.append_event("event-1", "device-1", "surface.push", {"revision": "abc"}, "same")
    second = store.append_event("event-2", "device-1", "surface.push", {"revision": "def"}, "same")
    assert first["event_id"] == second["event_id"] == "event-1"
    assert [event["event_id"] for event in store.events_after("device-1", 0)] == ["event-1"]
    assert store.events_after("device-1", first["seq"]) == []
    assert store.acknowledge("device-1", "event-1", "rendered", "abc", None)
    assert store.acknowledge("device-1", "event-1", "rendered", "abc", None)
    assert not store.acknowledge("device-2", "event-1", "rendered", "abc", None)


def test_every_connection_is_closed(settings, monkeypatch) -> None:
    real_connect = sqlite3.connect
    opened: list[sqlite3.Connection] = []

    def tracked_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(db_module.sqlite3, "connect", tracked_connect)
    store = Store(settings.data_dir / "connections.db")
    store.initialize()
    store.execute("INSERT INTO state(key,value) VALUES(?,?)", ("key", "value"))
    assert store.one("SELECT value FROM state WHERE key='key'") == {"value": "value"}
    assert store.all("SELECT key FROM state") == [{"key": "key"}]
    assert opened
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")
