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
    "MESSAGE_QUEUE_CONNECTION_LOST": re.compile(
        r"Kafka broker connection lost",
        re.IGNORECASE,
    ),
    "SSL_CERTIFICATE_EXPIRED": re.compile(
        r"SSL certificate has expired",
        re.IGNORECASE,
    ),
    "THREAD_POOL_EXHAUSTED": re.compile(
        r"Thread pool exhausted, no available workers",
        re.IGNORECASE,
    ),
    "RATE_LIMIT_EXCEEDED": re.compile(
        r"Rate limit exceeded for client requests",
        re.IGNORECASE,
    ),
    "AUTH_TOKEN_VALIDATION_FAILURE": re.compile(
        r"Failed to validate access token",
        re.IGNORECASE,
    ),
    "CONTAINER_OOM_KILLED": re.compile(
        r"Container killed by OOM killer",
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
