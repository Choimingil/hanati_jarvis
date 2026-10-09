import re


# These are follow-up effects emitted after the scenario's detectable root error.
# Keep them as logs rather than opening another UNKNOWN_ERROR incident.
SCENARIO_CONTEXT_MESSAGES = {
    "Unable to write application data.",
    "Service entering read-only mode.",
    "HTTP request aborted.",
    "Circuit breaker opened.",
    "Unable to execute SQL query.",
    "Request processing aborted.",
    "Payment service unavailable.",
    "Transaction cancelled.",
    "Application process terminated.",
    "Falling back to database.",
    "Database overloaded by cache fallback.",
    "Failed to publish order event.",
    "Order processing queue backed up.",
    "HTTPS handshake failed for incoming requests.",
    "Client connections rejected due to invalid certificate.",
    "Incoming requests rejected with 503.",
    "Request latency exceeded SLA.",
    "Requests throttled with HTTP 429.",
    "Downstream service overloaded by retry storm.",
    "User session authentication rejected.",
    "Protected endpoints returning 401.",
    "Pod restarted due to OOMKilled status.",
    "Service unavailable during pod restart.",
    "Order transaction rolled back after deadlock.",
    "Checkout requests failing with transaction error.",
    "Order lookup requests timing out.",
    "Health check endpoint returning 503.",
    "Stale order status returned to client.",
    "Order status inconsistency reported by downstream.",
    "Failed to accept new client connection.",
    "Application stopped serving new requests.",
    "Upstream marked as unavailable by health check.",
    "Order submission failing for all clients.",
    "Settlement callback not received for pending orders.",
    "Orders stuck in PENDING_PAYMENT state.",
    "Token expiry check rejecting valid sessions.",
    "Scheduled settlement batch skipped its window.",
    "Available replica count dropped below desired.",
    "Service capacity reduced, requests shedding.",
}


def _message_key(message):
    return re.sub(r"\s+", " ", str(message or "")).strip().rstrip(".").casefold()


_CONTEXT_MESSAGE_KEYS = {_message_key(message) for message in SCENARIO_CONTEXT_MESSAGES}


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
    "DB_DEADLOCK": re.compile(
        r"Deadlock detected while updating order rows",
        re.IGNORECASE,
    ),
    "CONNECTION_POOL_EXHAUSTED": re.compile(
        r"Connection pool exhausted, cannot acquire connection",
        re.IGNORECASE,
    ),
    "DB_REPLICATION_LAG": re.compile(
        r"Read replica replication lag exceeded threshold",
        re.IGNORECASE,
    ),
    "FILE_DESCRIPTOR_EXHAUSTED": re.compile(
        r"Too many open files",
        re.IGNORECASE,
    ),
    "UPSTREAM_GATEWAY_TIMEOUT": re.compile(
        r"HTTP 504 gateway timeout from upstream",
        re.IGNORECASE,
    ),
    "PAYMENT_GATEWAY_FAILURE": re.compile(
        r"Payment authorization failed at gateway",
        re.IGNORECASE,
    ),
    "CLOCK_SKEW_DETECTED": re.compile(
        r"Clock skew detected against NTP server",
        re.IGNORECASE,
    ),
    "POD_CRASHLOOP_BACKOFF": re.compile(
        r"Pod entered CrashLoopBackOff state",
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


def is_context_only_error(message, synthetic=False):
    # A recognized primary error must always retain its incident.
    return detect_error_code(str(message or "")) is None and (
        synthetic is True or _message_key(message) in _CONTEXT_MESSAGE_KEYS
    )


def is_context_only_incident(incident):
    if incident.get("error_code") not in {None, "UNKNOWN_ERROR"}:
        return False
    return is_context_only_error(
        incident.get("latest_message") or incident.get("representative_message")
        or incident.get("normalized_message") or "",
        synthetic=incident.get("synthetic") is True,
    )
