from datetime import UTC, datetime
from typing import Any
from operations.privacy import redact


def normalize_log(
    raw_log: dict[str, Any],
) -> dict[str, Any]:
    raw_log = redact(raw_log)
    level = str(
        raw_log.get("level", "")
    ).upper()

    message = (
        raw_log.get("message")
        or raw_log.get("log")
        or ""
    )

    service = (
        raw_log.get("service")
        or raw_log.get("application")
        or "unknown"
    )

    host = (
        raw_log.get("host")
        or raw_log.get("hostname")
        or raw_log.get("_HOSTNAME")
        or "unknown"
    )

    timestamp = (
        raw_log.get("timestamp")
        or raw_log.get("date")
        or datetime.now(UTC).isoformat()
    )

    return {
        "timestamp": timestamp,
        "level": level,
        "message": str(message),
        "host": str(host),
        "service": str(service),
        "environment": raw_log.get(
            "environment",
            "unknown",
        ),
        "raw": raw_log,
    }
