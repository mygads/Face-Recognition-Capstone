from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

_FORBIDDEN_LOG_FIELDS = {
    "access_token",
    "embedding",
    "face",
    "image",
    "password",
    "photo",
    "secret",
    "token",
    "vector",
}


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = getattr(record, "edge_fields", {})
        safe_fields = {
            key: value
            for key, value in fields.items()
            if key.lower() not in _FORBIDDEN_LOG_FIELDS
        }
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": getattr(record, "edge_event", record.getMessage()),
            **safe_fields,
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    **fields: str | int | float | bool | None,
) -> None:
    logger.log(level, event, extra={"edge_event": event, "edge_fields": fields})
