from __future__ import annotations

import socket
from dataclasses import replace

from spatial_ui_agent_server.discovery import DISCOVERY_REQUEST, Discovery, LanDiscoveryResponder


def test_discovery_binds_only_the_configured_laptop_interface(settings, monkeypatch) -> None:
    calls: dict = {}

    class FakeZeroconf:
        def __init__(self, **kwargs) -> None:
            self.settings = kwargs
            calls.setdefault("instances", []).append(self)

        def register_service(self, info) -> None:
            calls["registered"] = info

        def unregister_service(self, info) -> None:
            calls["unregistered"] = info

        def close(self) -> None:
            calls["closed"] = True

    monkeypatch.setattr("spatial_ui_agent_server.discovery.Zeroconf", FakeZeroconf)
    discovery = Discovery(
        replace(settings, mdns_enabled=True, mdns_address="192.0.2.44,198.51.100.7")
    )

    discovery.start()
    assert len(discovery.registrations) == 2
    interfaces = [registration[0] for registration in discovery.registrations]
    assert [item.settings["interfaces"] for item in interfaces] == [
        ["192.0.2.44"],
        ["198.51.100.7"],
    ]
    discovery.stop()
    assert calls["closed"] is True


def test_lan_discovery_response_contains_no_address() -> None:
    responder = LanDiscoveryResponder(http_port=8766, discovery_port=0)
    responder.start()
    try:
        assert responder.bound_port is not None
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(2)
            client.sendto(DISCOVERY_REQUEST, ("127.0.0.1", responder.bound_port))
            payload, source = client.recvfrom(256)
        assert source[0] == "127.0.0.1"
        assert payload == b"SPATIAL_UI_AGENT_V1 http 8766 spatial.surface.v1"
        assert b"127.0.0.1" not in payload
    finally:
        responder.stop()
