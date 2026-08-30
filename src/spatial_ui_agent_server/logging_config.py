from __future__ import annotations

import logging
from typing import Any

from .config import Settings


class OperatorPollingFilter(logging.Filter):
    quiet_paths = ("GET /admin/state ", "GET /admin/logs ")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(path in message for path in self.quiet_paths)


def build_logging_config(settings: Settings) -> dict[str, Any]:
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = {
        "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        "datefmt": "%Y-%m-%dT%H:%M:%S%z",
    }
    access_formatter = {
        "()": "uvicorn.logging.AccessFormatter",
        "fmt": '%(asctime)s %(levelprefix)s %(client_addr)s "%(request_line)s" %(status_code)s',
        "datefmt": "%Y-%m-%dT%H:%M:%S%z",
    }
    handlers: dict[str, Any] = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stdout",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "default",
            "filename": str(settings.log_file),
            "maxBytes": settings.log_max_bytes,
            "backupCount": settings.log_backup_count,
            "encoding": "utf-8",
        },
        "access_console": {
            "class": "logging.StreamHandler",
            "filters": ["operator_polling"],
            "formatter": "access",
            "stream": "ext://sys.stdout",
        },
        "access_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filters": ["operator_polling"],
            "formatter": "access",
            "filename": str(settings.log_file),
            "maxBytes": settings.log_max_bytes,
            "backupCount": settings.log_backup_count,
            "encoding": "utf-8",
        },
    }
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"default": formatter, "access": access_formatter},
        "filters": {
            "operator_polling": {
                "()": "spatial_ui_agent_server.logging_config.OperatorPollingFilter"
            }
        },
        "handlers": handlers,
        "loggers": {
            "uvicorn": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
            "uvicorn.error": {
                "handlers": ["console", "file"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["access_console", "access_file"],
                "level": "INFO",
                "propagate": False,
            },
            "spatial_ui_agent_server": {
                "handlers": ["console", "file"],
                "level": "INFO",
                "propagate": False,
            },
        },
        "root": {"handlers": ["console", "file"], "level": "INFO"},
    }
