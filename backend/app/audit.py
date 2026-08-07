"""Structured audit logging for access to pupil records.

Emits one JSON line per security-relevant event. Two hard rules:

  * Never log dictation text, observation bodies, or passwords. Log *identifiers*
    so an event can be tied to a record, not the record's contents.
  * Never log a full pupil name. `student_id` is enough to reconstruct who,
    given database access — the log itself stays free of personal data.
"""
import json
import logging
import uuid
from typing import Any

logger = logging.getLogger("muendlich.audit")


class JsonFormatter(logging.Formatter):
    """Minimal JSON lines formatter — no dependency on structlog/python-json-logger."""

    _RESERVED = frozenset(
        vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()
    ) | {"taskName", "message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                payload[key] = _jsonable(value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    # Replace any handler installed by uvicorn's default config.
    root.handlers = [handler]
    root.setLevel(level)
    for name in ("uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).handlers = [handler]
        logging.getLogger(name).propagate = False


def audit(action: str, *, actor: uuid.UUID | str | None = None, **fields: Any) -> None:
    """Record one audit event.

    Callers pass identifiers only — see the module docstring.
    """
    logger.info(action, extra={"action": action, "actor": str(actor) if actor else None, **fields})
