"""Read-only, administrator-registered business KPI probe. Never submits a transaction."""

from datetime import UTC, datetime
import math
import os
from urllib.parse import urlparse
import httpx


def validate_probe(policy):
    if not isinstance(policy, dict):
        raise ValueError("business recovery policy required")
    url = urlparse(policy.get("url", ""))
    allowed = policy.get("allowed_hosts", [])
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.hostname not in allowed
        or url.username
        or url.password
        or url.fragment
    ):
        raise ValueError("business probe URL must match administrator allowlist")
    if url.scheme == "http" and not policy.get("allow_internal_http", False):
        raise ValueError("HTTPS required for business probe")
    if not policy.get("expected_service") or not policy.get("expected_environment"):
        raise ValueError("business probe identity required")
    criteria = policy.get("criteria", {})
    required = {
        "success_rate_min",
        "failure_rate_max",
        "p95_latency_ms_max",
        "transactions_min",
    }
    if not required.issubset(criteria):
        raise ValueError("complete business KPI criteria required")
    for key in required:
        value = criteria[key]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError("invalid KPI threshold")
    if (
        criteria["transactions_min"] < 1
        or criteria["success_rate_min"] > 1
        or criteria["failure_rate_max"] > 1
    ):
        raise ValueError("invalid business KPI coverage")
    return policy


def verify_business(policy, execution_started_at, http=None, now=None):
    checks = []
    try:
        validate_probe(policy)
        headers = {}
        if policy.get("token_env"):
            token = os.environ.get(policy["token_env"], "")
            if not token:
                raise ValueError("business probe credential missing")
            headers["Authorization"] = "Bearer " + token

        def fetch(client):
            with client.stream(
                "GET", policy["url"], headers=headers, timeout=5
            ) as response:
                response.raise_for_status()
                body = b""
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) > 65536:
                        raise ValueError("business probe response too large")
                import json

                return json.loads(body)

        if http is None:
            with httpx.Client(trust_env=False, follow_redirects=False) as client:
                data = fetch(client)
        else:
            data = fetch(http)
        checks.append(
            {
                "name": "business:identity",
                "passed": data.get("service") == policy["expected_service"]
                and data.get("environment") == policy["expected_environment"],
            }
        )
        current = now or datetime.now(UTC)
        sampled = datetime.fromisoformat(data["sampled_at"].replace("Z", "+00:00"))
        window = datetime.fromisoformat(
            data["window_started_at"].replace("Z", "+00:00")
        )
        if sampled.tzinfo is None or window.tzinfo is None:
            raise ValueError("timezone-aware KPI timestamps required")
        age = (current - sampled).total_seconds()
        fresh = (
            0 <= age <= min(300, max(1, policy.get("max_age_seconds", 120)))
            and execution_started_at <= window.timestamp() <= sampled.timestamp()
        )
        checks.append({"name": "business:fresh_post_action_window", "passed": fresh})
        criteria = policy["criteria"]
        for field, threshold, minimum in [
            ("success_rate", criteria["success_rate_min"], True),
            ("failure_rate", criteria["failure_rate_max"], False),
            ("p95_latency_ms", criteria["p95_latency_ms_max"], False),
            ("transactions", criteria["transactions_min"], True),
        ]:
            value = data.get(field)
            valid = (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and value >= 0
            )
            if field == "transactions":
                valid = valid and value == int(value)
            if field in {"success_rate", "failure_rate"}:
                valid = valid and value <= 1
            checks.append(
                {
                    "name": "business:" + field,
                    "passed": bool(
                        valid
                        and (value >= threshold if minimum else value <= threshold)
                    ),
                    "observed": value if valid else None,
                    "threshold": threshold,
                }
            )
    except Exception as exc:
        checks.append(
            {
                "name": "business:probe_available",
                "passed": False,
                "reason": type(exc).__name__,
            }
        )
    return checks
