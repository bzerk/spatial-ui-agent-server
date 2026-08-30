from __future__ import annotations

import ipaddress
import logging
import socket
import threading

from zeroconf import IPVersion, ServiceInfo, Zeroconf

from .config import Settings

LOGGER = logging.getLogger(__name__)
DISCOVERY_REQUEST = b"SPATIAL_UI_DISCOVER_V1"
DISCOVERY_RESPONSE_PREFIX = "SPATIAL_UI_AGENT_V1"


class LanDiscoveryResponder:
    def __init__(self, http_port: int, discovery_port: int) -> None:
        self.http_port = http_port
        self.discovery_port = discovery_port
        self.socket: socket.socket | None = None
        self.thread: threading.Thread | None = None
        self.stopping = threading.Event()
        self.seen_clients: set[str] = set()

    @property
    def bound_port(self) -> int | None:
        return self.socket.getsockname()[1] if self.socket else None

    def start(self) -> None:
        if self.socket is not None:
            return
        candidate = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        candidate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        candidate.settimeout(0.5)
        candidate.bind(("0.0.0.0", self.discovery_port))
        self.stopping.clear()
        self.seen_clients.clear()
        self.socket = candidate
        self.thread = threading.Thread(
            target=self._serve,
            name="spatial-lan-discovery",
            daemon=True,
        )
        self.thread.start()

    def stop(self) -> None:
        self.stopping.set()
        candidate = self.socket
        self.socket = None
        if candidate:
            candidate.close()
        thread = self.thread
        self.thread = None
        if thread and thread is not threading.current_thread():
            thread.join(timeout=1.5)

    def _serve(self) -> None:
        response = (f"{DISCOVERY_RESPONSE_PREFIX} http {self.http_port} spatial.surface.v1").encode(
            "ascii"
        )
        while not self.stopping.is_set():
            candidate = self.socket
            if candidate is None:
                return
            try:
                payload, sender = candidate.recvfrom(256)
                if payload.strip() != DISCOVERY_REQUEST:
                    continue
                candidate.sendto(response, sender)
                if sender[0] not in self.seen_clients:
                    self.seen_clients.add(sender[0])
                    LOGGER.info("LAN discovery resolved client=%s", sender[0])
            except TimeoutError:
                continue
            except OSError:
                if not self.stopping.is_set():
                    LOGGER.exception("LAN discovery responder stopped unexpectedly")
                return


class Discovery:
    service_type = "_spatial-ui._tcp.local."

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.registrations: list[tuple[Zeroconf, ServiceInfo]] = []
        self.lan = LanDiscoveryResponder(settings.port, settings.lan_discovery_port)

    def start(self) -> None:
        if self.settings.lan_discovery_enabled:
            self.lan.start()
        if not self.settings.mdns_enabled:
            return
        addresses = tuple(
            dict.fromkeys(
                item.strip()
                for item in (self.settings.mdns_address or self._local_address()).split(",")
                if item.strip()
            )
        )
        for address in addresses:
            info = ServiceInfo(
                self.service_type,
                f"{self.settings.mdns_name}.{self.service_type}",
                addresses=[ipaddress.ip_address(address).packed],
                port=self.settings.port,
                properties={
                    "api": "/v1",
                    "ws": "/v1/devices/{id}/events",
                    "contract": "spatial.surface.v1",
                    "scheme": "http",
                },
                server=f"{socket.gethostname()}.local.",
            )
            zeroconf = Zeroconf(interfaces=[address], ip_version=IPVersion.V4Only)
            zeroconf.register_service(info)
            self.registrations.append((zeroconf, info))

    def stop(self) -> None:
        self.lan.stop()
        for zeroconf, info in self.registrations:
            zeroconf.unregister_service(info)
            zeroconf.close()
        self.registrations.clear()

    @staticmethod
    def _local_address() -> str:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            try:
                sock.connect(("192.0.2.1", 9))
                return str(sock.getsockname()[0])
            except OSError:
                return "127.0.0.1"
