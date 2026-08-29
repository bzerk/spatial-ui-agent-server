from __future__ import annotations

import ipaddress
import socket

from zeroconf import IPVersion, ServiceInfo, Zeroconf

from .config import Settings


class Discovery:
    service_type = "_spatial-ui._tcp.local."

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.zeroconf: Zeroconf | None = None
        self.info: ServiceInfo | None = None

    def start(self) -> None:
        if not self.settings.mdns_enabled:
            return
        address = self.settings.mdns_address or self._local_address()
        self.info = ServiceInfo(
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
        self.zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
        self.zeroconf.register_service(self.info)

    def stop(self) -> None:
        if self.zeroconf and self.info:
            self.zeroconf.unregister_service(self.info)
            self.zeroconf.close()
        self.zeroconf = None
        self.info = None

    @staticmethod
    def _local_address() -> str:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            try:
                sock.connect(("192.0.2.1", 9))
                return str(sock.getsockname()[0])
            except OSError:
                return "127.0.0.1"
