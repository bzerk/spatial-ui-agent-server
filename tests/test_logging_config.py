from __future__ import annotations

import logging

from spatial_ui_agent_server.logging_config import OperatorPollingFilter, build_logging_config


def test_logging_config_uses_rotating_file(settings) -> None:
    config = build_logging_config(settings)

    assert settings.log_file.parent.is_dir()
    assert config["handlers"]["file"]["filename"] == str(settings.log_file)
    assert config["handlers"]["file"]["maxBytes"] == settings.log_max_bytes
    assert config["handlers"]["file"]["backupCount"] == settings.log_backup_count
    assert "file" in config["loggers"]["uvicorn"]["handlers"]


def test_operator_polling_filter_keeps_the_log_useful() -> None:
    filter_ = OperatorPollingFilter()
    polling = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, "GET /admin/logs HTTP/1.1", (), None
    )
    useful = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, "POST /admin/actions HTTP/1.1", (), None
    )

    assert filter_.filter(polling) is False
    assert filter_.filter(useful) is True
