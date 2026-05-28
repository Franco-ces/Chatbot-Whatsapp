# src/logging_config.py
"""
Configuración centralizada de logging estructurado con structlog.

Uso:
    from logging_config import setup_logging, get_logger
    setup_logging()
    logger = get_logger()
"""
import os
import sys
import contextvars
import structlog

# Context variable for request correlation
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


def _add_request_id(logger, method_name, event_dict):
    """Inject request_id into every log entry."""
    try:
        event_dict["request_id"] = request_id_ctx.get()
    except LookupError:
        event_dict["request_id"] = "-"
    return event_dict


def _drop_sensitive_fields(logger, method_name, event_dict):
    """Remove fields that should never appear in structured logs."""
    for field in ("password", "token", "api_key", "apikey", "secret"):
        event_dict.pop(field, None)
    return event_dict


def setup_logging():
    """
    Initialize structlog with JSON rendering.
    Call once at application startup (before any logger is used).
    """
    import logging
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    level_number = getattr(logging, log_level, logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _add_request_id,
            _drop_sensitive_fields,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Set stdlib logging minimum level so structlog processors actually run
    logging.basicConfig(format="%(message)s", level=level_number)


def get_logger(name: str | None = None):
    """Get a bound logger instance."""
    return structlog.get_logger(name)
