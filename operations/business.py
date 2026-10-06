"""Business impact policy. Input impact is reported evidence, not verified facts."""

import json
import math
import os
from pathlib import Path


def service_policy(environment, service):
    path = Path(os.getenv("BUSINESS_SERVICES_FILE", "business-services.json"))
    if not path.exists():
        return {}
    config = json.loads(path.read_text())
    return next(
        (
            p
            for p in config.get("services", [])
            if p.get("environment") == environment and p.get("service") == service
        ),
        {},
    )


def business_priority(log, count=1, previous=None):
    policy = service_policy(
        log.get("environment", "unknown"), log.get("service", "unknown")
    )
    impact = dict((previous or {}).get("business_impact") or {})
    supplied = (
        log.get("business_impact") or log.get("raw", {}).get("business_impact") or {}
    )
    if not isinstance(supplied, dict):
        supplied = {}
    for field in (
        "failed_transactions",
        "affected_customers",
        "failure_rate",
        "p95_latency_ms",
    ):
        value = supplied.get(field)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value >= 0
            and (field != "failure_rate" or value <= 1)
        ):
            impact[field] = max(impact.get(field, 0), value)
    if supplied.get("service_available") is False:
        impact["service_available"] = False
    rank = 3
    reasons = []
    if policy.get("criticality") == "tier1":
        rank = 2
        reasons.append("등록된 핵심 업무 서비스")
    if impact.get("service_available") is False:
        rank = 1
        reasons.append("업무 중단 보고")
    if (
        impact.get("failed_transactions", 0) > 0
        or impact.get("affected_customers", 0) > 0
    ):
        rank = min(rank, 2)
        reasons.append("실패 거래 또는 영향 고객 보고")
    thresholds = policy.get("priority_thresholds", {})
    for field, default in [
        ("failed_transactions", 100),
        ("affected_customers", 100),
        ("failure_rate", 0.1),
        ("p95_latency_ms", 5000),
    ]:
        threshold = thresholds.get(field, default)
        if (
            isinstance(threshold, (int, float))
            and not isinstance(threshold, bool)
            and threshold > 0
            and impact.get(field, 0) >= threshold
        ):
            rank = 1
            reasons.append(field + " 긴급 기준 초과")
    if count >= 20:
        rank = min(rank, 2)
        reasons.append("반복 오류 20회 이상")
    rank = min(rank, (previous or {}).get("priority_rank", 4))
    if not reasons:
        reasons = ["업무 영향 미확인: 운영자 확인 필요"]
    return {
        "priority": "P" + str(rank),
        "priority_rank": rank,
        "priority_reasons": reasons,
        "business_impact": impact,
        "impact_evidence": "reported",
        "business_criticality": policy.get("criticality", "unclassified"),
    }
