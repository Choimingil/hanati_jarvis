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
