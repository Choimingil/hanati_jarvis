import re


ERROR_PATTERNS = {
    "ORA-28040": re.compile(
        r"\bORA-28040\b",
        re.IGNORECASE,
    ),
    "DISK_FULL": re.compile(
        r"No space left on device",
        re.IGNORECASE,
    ),
    "DNS_RESOLUTION_FAILURE": re.compile(
        r"Failed to resolve service endpoint",
        re.IGNORECASE,
    ),
    "DB_CONNECTION_FAILURE": re.compile(
        r"Database connection failed",
        re.IGNORECASE,
    ),
    "EXTERNAL_API_FAILURE": re.compile(
        r"HTTP 503 from external API",
        re.IGNORECASE,
    ),
    "MEMORY_LEAK": re.compile(
        r"OutOfMemoryError",
        re.IGNORECASE,
    ),
    "REDIS_CONNECTION_FAILURE": re.compile(
        r"Redis connection lost",
        re.IGNORECASE,
    ),
}


def detect_error_code(
    message: str,
) -> str | None:
    if not message:
        return None

    for error_code, pattern in ERROR_PATTERNS.items():
        if pattern.search(message):
            return error_code

    return None
