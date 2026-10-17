"""Structured JSON logging to stdout (Railway captures it) and optionally to logs/conversations.log."""
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        payload = getattr(record, "payload", None)
        if payload is not None:
            entry["payload"] = payload
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    root.handlers.clear()
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(JsonFormatter())
    root.addHandler(stream)
    if settings.log_to_file:
        Path("logs").mkdir(exist_ok=True)
        fh = logging.FileHandler("logs/conversations.log")
        fh.setFormatter(JsonFormatter())
        root.addHandler(fh)
    logging.getLogger("uvicorn.access").setLevel("WARNING")
