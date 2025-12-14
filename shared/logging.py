
import contextvars
import datetime as dt
import json
import logging.handlers
import logging
import os
import sys
from typing import Any

# Global context for correlation IDs across services
_REQUEST_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

_SENSITIVE_ENV_VARS = [
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "OPS_API_TOKEN",
    "GEMINI_API_KEY",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "GRAFANA_ADMIN_PASSWORD"
]

def _load_sensitive_values() -> set[str]:
    """Load sensitive values from env vars to redact."""
    values: set[str] = set()
    for name in _SENSITIVE_ENV_VARS:
        value = (os.getenv(name) or "").strip()
        if value:
            values.add(value)
    return values

class JsonFormatter(logging.Formatter):
    """
    JSON formatter that:
    1. Redacts sensitive keys/values
    2. Includes correlation IDs
    3. Standardizes timestamp format
    """
    redaction_keys = {"api_key", "secret", "token", "signature", "passphrase", "password", "key"}

    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name
        self._sensitive_values = _load_sensitive_values()

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": dt.datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "service": self.service_name,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        
        # Inject correlation ID if present
        request_id = _REQUEST_ID.get()
        if request_id:
            payload["correlation_id"] = request_id
            
        if hasattr(record, "event"):
            payload["event"] = record.event
            
        if record.exc_info:
            payload["stack"] = self.formatException(record.exc_info)
            
        return json.dumps(self._redact(payload), default=str)

    def _redact(self, payload: dict[str, Any]) -> dict[str, Any]:
        scrubbed: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, str):
                # 1. Check if key itself is sensitive (e.g. env var dump)
                lowered_key = key.lower()
                if lowered_key in self.redaction_keys:
                    scrubbed[key] = "***redacted***"
                    continue
                
                # 2. Scrub the string value for known secrets
                scrubbed_val = value
                for secret in self._sensitive_values:
                    if secret and secret in scrubbed_val:
                        scrubbed_val = scrubbed_val.replace(secret, "***redacted***")
                scrubbed[key] = scrubbed_val
            else:
                scrubbed[key] = value
        return scrubbed

def setup_logging(service_name: str, level: int = logging.INFO) -> None:
    """Configures the root logger with the standard JSON formatter."""
    # Remove existing handlers
    root = logging.getLogger()
    if root.handlers:
        for handler in root.handlers:
            root.removeHandler(handler)
            
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service_name))
    root.addHandler(handler)
    # Add File Handler (for log viewer)
    # Robust path selection: Docker (/app/data) vs Local (./data)
    log_dir = os.getenv("LOG_DIR", "/app/data/logs")
    
    # If /app doesn't exist or isn't writable, fallback to local ./data/logs
    if log_dir.startswith("/app") and not os.path.exists("/app"):
        log_dir = "data/logs"

    try:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            filename=f"{log_dir}/system.jsonl",
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=3
        )
        file_handler.setFormatter(JsonFormatter(service_name))
        root.addHandler(file_handler)
    except OSError:
        # Fallback to no file logging if permissions fail
        pass

    root.setLevel(level)
    root.setLevel(level)

    # Silence noisy libs
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.error").handlers = []
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)

def bind_request_id(request_id: str) -> contextvars.Token[str | None]:
    return _REQUEST_ID.set(request_id)

def reset_request_context(token: contextvars.Token[str | None]) -> None:
    try:
        _REQUEST_ID.reset(token)
    except LookupError:
        pass
