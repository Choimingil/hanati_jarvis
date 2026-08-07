"""웹 콘솔의 "분석" 버튼이 log_generator/main.py와 같은 방식(시나리오
실행 -> fluentbit가 tail하는 파일에 기록)으로 동작하도록 하는 라우트.

실제 탐지/진단/추천은 fluent-bit가 파일을 tail해서 POST /api/v1/logs로
전달한 뒤 비동기로 이뤄지므로, 이 블루프린트는 (1) 시나리오를 트리거하고
(2) Elasticsearch에 쌓인 추천 결과 중 가장 최근 것을 폴링해서 보여주는
두 엔드포인트로 구성된다.
"""

import hashlib
import subprocess
import sys
from pathlib import Path

from flask import Blueprint, jsonify, request

from config import ELASTIC_RECOMMENDATION_INDEX
from elastic.client import get_client
from utils.time_utils import now_iso

# scripts/dev_infra.sh가 띄우는 컨테이너 이름과 일치해야 한다.
FLUENTBIT_CONTAINER = "hanati-fluentbit"
ES_CONTAINER = "hanati-es"
QDRANT_CONTAINER = "hanati-qdrant"

LOG_GENERATOR_DIR = (
    Path(__file__).resolve().parent.parent / "log_generator"
)
if str(LOG_GENERATOR_DIR) not in sys.path:
    sys.path.insert(0, str(LOG_GENERATOR_DIR))

from registry import SCENARIO_REGISTRY  # noqa: E402
from trigger import run_scenario  # noqa: E402


log_generator_blueprint = Blueprint(
    "log_generator", __name__
)


@log_generator_blueprint.get(
    "/api/v1/log-generator/scenarios"
)
def list_scenarios():
    return jsonify([
        {"key": key, "label": label}
        for key, (_, label, _) in SCENARIO_REGISTRY.items()
    ])


@log_generator_blueprint.post(
    "/api/v1/log-generator/run"
)
def run():
    body = request.get_json(silent=True) or {}
    key = body.get("scenario")

    if key not in SCENARIO_REGISTRY:
        return jsonify({
            "status": "invalid_request",
            "reason": "unknown scenario",
        }), 400

    triggered_at = now_iso()
    result = run_scenario(key)

    return jsonify({
        "status": "triggered",
        "triggered_at": triggered_at,
        "error_code": result["error_code"],
        "events": result["events"],
    })


@log_generator_blueprint.get(
    "/api/v1/log-generator/latest-recommendation"
)
def latest_recommendation():
    error_code = request.args.get("error_code")
    since = request.args.get("since")

    if not error_code or not since:
        return jsonify({
            "status": "invalid_request",
        }), 400

    client = get_client()

    try:
        response = client.search(
            index=ELASTIC_RECOMMENDATION_INDEX,
            query={
                "bool": {
                    "should": [
                        {"match": {
                            "recommendation.error_code": error_code
                        }},
                        {"match": {
                            "guidance.original_error_code": error_code
                        }},
                    ],
                    "minimum_should_match": 1,
                }
            },
            size=20,
            # 첫 추천이 저장되기 전엔 이 인덱스가 아직 없다 - 없어도
            # 404 대신 빈 결과로 받아서 폴링 중 정상 상태로 취급한다.
            ignore_unavailable=True,
        )
    except Exception:
        return jsonify({"status": "pending"})

    hits = response["hits"]["hits"]
    fresh = [
        hit["_source"]
        for hit in hits
        if hit["_source"].get("timestamp", "") > since
    ]

    if not fresh:
        return jsonify({"status": "pending"})

    latest = max(fresh, key=lambda doc: doc["timestamp"])

    return jsonify({
        "status": "ready",
        "recommendation": (
            latest.get("recommendation")
            or latest.get("guidance")
        ),
    })


@log_generator_blueprint.get(
    "/api/v1/log-generator/incidents"
)
def recent_incidents():
    """최근 추천 결과를 운영자용 장애 목록으로 집계한다."""
    minutes = request.args.get("minutes", default=60, type=int)
    minutes = max(1, min(minutes or 60, 1440))
    client = get_client()

    try:
        response = client.search(
            index=ELASTIC_RECOMMENDATION_INDEX,
            query={
                "range": {
                    "timestamp": {
                        "gte": f"now-{minutes}m",
                    }
                }
            },
            sort=[{"timestamp": "desc"}],
            size=500,
            ignore_unavailable=True,
        )
    except Exception:
        return jsonify({
            "status": "unavailable",
            "incidents": [],
        })

    grouped = {}
    for hit in response.get("hits", {}).get("hits", []):
        source = hit.get("_source", {})
        log = source.get("log") or {}
        recommendation = (
            source.get("recommendation")
            or source.get("guidance")
            or {}
        )
        error_code = (
            recommendation.get("error_code")
            or recommendation.get("primary_problem_code")
            or recommendation.get("original_error_code")
            or "UNKNOWN_ERROR"
        )
        service = str(log.get("service") or "unknown")
        environment = str(log.get("environment") or "unknown")
        message = str(log.get("message") or "")
        fingerprint_source = "|".join([
            environment,
            service,
            error_code,
            message[:160],
        ])
        incident_id = "INC-" + hashlib.sha1(
            fingerprint_source.encode("utf-8")
        ).hexdigest()[:10].upper()
        timestamp = source.get("timestamp") or log.get("timestamp") or ""
        host = str(log.get("host") or "unknown")

        incident = grouped.setdefault(incident_id, {
            "incident_id": incident_id,
            "service": service,
            "environment": environment,
            "error_code": error_code,
            "message": message,
            "count": 0,
            "hosts": set(),
            "first_seen": timestamp,
            "last_seen": timestamp,
            "status": "ACTION_REQUIRED",
            "recommendation": recommendation,
        })
        incident["count"] += 1
        incident["hosts"].add(host)
        incident["first_seen"] = min(
            incident["first_seen"], timestamp
        )
        if timestamp >= incident["last_seen"]:
            incident["last_seen"] = timestamp
            incident["recommendation"] = recommendation

    incidents = []
    for incident in grouped.values():
        count = incident["count"]
        incident["hosts"] = sorted(incident["hosts"])
        incident["host_count"] = len(incident["hosts"])
        incident["severity"] = (
            "CRITICAL" if count >= 20
            else "HIGH" if count >= 5
            else "MEDIUM"
        )
        incidents.append(incident)

    incidents.sort(
        key=lambda item: item["last_seen"],
        reverse=True,
    )
    return jsonify({
        "status": "ready",
        "incidents": incidents,
    })


def _container_tail(
    container: str, since: str | None = None, lines: int = 60
) -> list[str]:
    cmd = ["docker", "logs"]
    # since가 있으면(=이번 트리거 이후) 그 시점부터만, 없으면 기존처럼
    # 마지막 N줄 (과거 실행분이 섞여 보이는 걸 막기 위한 기본 스코프)
    if since:
        cmd += ["--since", since]
    else:
        cmd += ["--tail", str(lines)]
    cmd.append(container)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        return []

    output = result.stdout + result.stderr
    return [
        line
        for line in output.splitlines()
        if line.strip()
    ]


@log_generator_blueprint.get(
    "/api/v1/log-generator/activity"
)
def activity():
    since = request.args.get("since")

    return jsonify({
        "fluentbit_log": _container_tail(
            FLUENTBIT_CONTAINER, since
        ),
        "qdrant_log": _container_tail(
            QDRANT_CONTAINER, since
        ),
        "elasticsearch_log": _container_tail(
            ES_CONTAINER, since
        ),
    })
