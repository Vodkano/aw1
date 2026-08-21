"""Logging estructurado con redaccion de secretos e id de peticion."""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar

request_id: ContextVar[str] = ContextVar("request_id", default="-")

_PATTERNS = (
    (re.compile(r"sk-[A-Za-z0-9_\-]{10,}"), "***"),
    (re.compile(r"(?i)(api[_-]?key\"?\s*[:=]\s*\"?)([^\s\",;]+)"), r"\1***"),
    (re.compile(r"(?i)(authorization\"?\s*[:=]\s*\"?)(bearer\s+)?([^\s\",;]+)"), r"\1***"),
    (re.compile(r"(?i)(token\"?\s*[:=]\s*\"?)([^\s\",;]{6,})"), r"\1***"),
    (re.compile(r"(https?://)[^/\s:@]+:[^/\s@]+@"), r"\1***:***@"),
)


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class _IdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.rid = request_id.get()
        return True


class ConsoleFormatter(logging.Formatter):
    COLORS = {"DEBUG": "\033[90m", "INFO": "\033[36m", "WARNING": "\033[33m",
              "ERROR": "\033[31m", "CRITICAL": "\033[35m"}

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        reset = "\033[0m" if color else ""
        base = super().format(record)
        return redact(f"{color}{base}{reset}")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "rid": getattr(record, "rid", "-"),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return redact(json.dumps(payload, ensure_ascii=False))


def configure_logging(level: str = "INFO", as_json: bool = False) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_IdFilter())
    handler.setFormatter(
        JsonFormatter()
        if as_json
        else ConsoleFormatter("%(asctime)s %(levelname)-7s %(name)-22s %(message)s", "%H:%M:%S")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
