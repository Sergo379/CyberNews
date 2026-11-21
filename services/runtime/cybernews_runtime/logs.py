import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "service": self.service_name,
            "level": record.levelname,
            "request_id": request_id.get(),
            "message": record.getMessage(),
        }
        for field in ("method", "status", "duration_ms", "error_type"):
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(service_name: str, level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service_name))
    logging.basicConfig(level=level, handlers=[handler], force=True)
