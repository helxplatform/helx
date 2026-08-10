import json
import logging
import traceback
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """
    Custom JSON formatter for structured logging.

    Outputs log records as JSON objects with standardized fields for easy parsing
    by log aggregation tools (ELK, Splunk, CloudWatch, etc.).
    """

    def format(self, record):
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "thread": record.threadName,
            "process": record.process,
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info),
            }

        # Add any extra fields that were passed to the logger
        # (e.g., logger.info("message", extra={"user": "john"}))
        if hasattr(record, "__dict__"):
            # Standard log record attributes to exclude from extra fields
            standard_attrs = {
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "message", "pathname", "process", "processName", "relativeCreated",
                "thread", "threadName", "exc_info", "exc_text", "stack_info",
            }

            extra_fields = {}
            for key, value in record.__dict__.items():
                if key not in standard_attrs and not key.startswith("_"):
                    try:
                        # Ensure value is JSON serializable
                        json.dumps(value)
                        extra_fields[key] = value
                    except (TypeError, ValueError):
                        # If not serializable, convert to string
                        extra_fields[key] = str(value)

            if extra_fields:
                log_data["extra"] = extra_fields

        # Return as compact JSON (one line per log entry)
        return json.dumps(log_data, default=str)
