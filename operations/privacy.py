"""Bounded, recursive redaction before storage, transport and LLM calls."""

import re

SENSITIVE = re.compile(
    r"password|passwd|secret|token|authorization|cookie|api[_-]?key|cvc|cvv|주민|비밀번호",
    re.I,
)
PATTERNS = [
    (re.compile(r"\bBearer\s+[^\s\"']+", re.I), "Bearer [REDACTED]"),
    (
        re.compile(
            r"(?i)((?:password|passwd|secret|token|api[_-]?key|cvc|cvv)[\"\']?\s*[:=]\s*[\"\']?)[^\s,;\"'}]+"
        ),
        r"\1[REDACTED]",
    ),
    (re.compile(r"\b\d{6}[- ]?[1-4]\d{6}\b"), "[RRN]"),
    (re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"), "[CARD_OR_ACCOUNT]"),
    (re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I), "[EMAIL]"),
    (re.compile(r"\b01[016789][- ]?\d{3,4}[- ]?\d{4}\b"), "[PHONE]"),
    (re.compile(r"(https?://)[^/\s:@]+:[^/\s@]+@"), r"\1[REDACTED]@"),
]

OPAQUE_KEYS = {
    "job_id",
    "job_ids",
    "execution_id",
    "incident_id",
    "recommendation_id",
    "action_id",
    "ingestion_id",
    "policy_digest",
    "preflight_id",
    "guidance_id",
    "script_id",
    "container_id",
    "image_id",
}
OPAQUE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,200}\Z")


def redact_field(key, value, depth):
    if key in OPAQUE_KEYS:
        if isinstance(value, str) and OPAQUE_ID.fullmatch(value):
            return value
        if isinstance(value, list) and all(
            isinstance(v, str) and OPAQUE_ID.fullmatch(v) for v in value
        ):
            return value[:1000]
    return redact(value, depth)


def redact(value, depth=0):
    if depth > 20:
        return "[DEPTH_LIMIT]"
    if isinstance(value, dict):
        return {
            str(k): "[REDACTED]"
            if SENSITIVE.search(str(k))
            else redact_field(str(k), v, depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v, depth + 1) for v in value[:1000]]
    if isinstance(value, str):
        for pattern, replacement in PATTERNS:
            value = pattern.sub(replacement, value)
        return value[:16000]
    return value
