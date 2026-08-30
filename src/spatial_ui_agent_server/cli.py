from __future__ import annotations

import uvicorn

from .config import Settings
from .logging_config import build_logging_config


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run(
        "spatial_ui_agent_server.api:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
        log_config=build_logging_config(settings),
    )


if __name__ == "__main__":
    main()
