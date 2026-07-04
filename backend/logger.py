
"""
Structured logging with redaction for Primus backend.
"""
import json
import logging
import logging.handlers
from datetime import datetime
from pathlib import Path

from backend.constants import (
    LOG_DIR,
    LOG_STREAMS,
    DEFAULT_LOG_MAX_BYTES,
    DEFAULT_LOG_BACKUP_COUNT,
)


# Keep track of resolved secrets to redact them
_resolved_secrets = set()


def register_secret(secret):
    """
    Register a secret to be redacted in logs.

    Args:
        secret: The secret string to redact
    """
    if secret:
        _resolved_secrets.add(secret)


def redact(value):
    """
    Redact any registered secrets from the value.

    Args:
        value: The value to redact

    Returns:
        Redacted value
    """
    if isinstance(value, str):
        for secret in _resolved_secrets:
            if secret in value:
                value = value.replace(secret, "***")
        return value
    elif isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    elif isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    else:
        return value


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record):
        # Get timestamp with microseconds using datetime
        dt = datetime.fromtimestamp(record.created)
        timestamp = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond:06d}Z"

        log_data = {
            "timestamp": timestamp,
            "level": record.levelname,
            "name": record.name,
            "message": redact(record.getMessage()),
        }

        if record.exc_info:
            log_data["exc_info"] = redact(self.formatException(record.exc_info))

        return json.dumps(log_data)


def get_logger(name, stream="errors"):
    """
    Get a logger for a specific stream.

    Args:
        name: Name of the logger
        stream: Log stream to use (one of LOG_STREAMS)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(f"{stream}.{name}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # Don't propagate to root logger

    # Only add handlers if not already added
    if not logger.handlers:
        # Ensure log directory exists
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        # File handler
        file_handler = logging.handlers.RotatingFileHandler(
            filename=LOG_DIR / f"{stream}.log",
            maxBytes=DEFAULT_LOG_MAX_BYTES,
            backupCount=DEFAULT_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(JSONFormatter())
        logger.addHandler(file_handler)

        # Console handler for errors only
        if stream == "errors":
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.WARNING)
            console_handler.setFormatter(JSONFormatter())
            logger.addHandler(console_handler)

    return logger


def get_ai_requests_logger(name):
    """Get logger for AI requests."""
    return get_logger(name, "ai_requests")


def get_tool_calls_logger(name):
    """Get logger for tool calls."""
    return get_logger(name, "tool_calls")


def get_errors_logger(name):
    """Get logger for errors."""
    return get_logger(name, "errors")


def get_jobs_logger(name):
    """Get logger for jobs."""
    return get_logger(name, "jobs")


def get_notifications_logger(name):
    """Get logger for notifications."""
    return get_logger(name, "notifications")


def get_metrics_logger(name):
    """Get logger for metrics."""
    return get_logger(name, "metrics")


def get_health_logger(name):
    """Get logger for health checks."""
    return get_logger(name, "health")


def get_diagnostics_logger(name):
    """Get logger for diagnostics."""
    return get_logger(name, "diagnostics")


def get_recovery_logger(name):
    """Get logger for recovery."""
    return get_logger(name, "recovery")

