"""웹 콘솔의 "분석" 버튼이 log_generator/main.py와 같은 방식(시나리오
실행 -> fluentbit가 tail하는 파일에 기록)으로 동작하도록 하는 라우트.

실제 탐지/진단/추천은 fluent-bit가 파일을 tail해서 POST /api/v1/logs로
전달한 뒤 비동기로 이뤄지므로, 이 블루프린트는 (1) 시나리오를 트리거하고
(2) Elasticsearch에 쌓인 추천 결과 중 가장 최근 것을 폴링해서 보여주는
두 엔드포인트로 구성된다.
"""

import json
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from flask import Blueprint, jsonify, request

from config import ELASTIC_INCIDENT_INDEX, ELASTIC_RECOMMENDATION_INDEX
from elastic.client import get_client
from utils.time_utils import now_iso

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
    """영속화된 운영 Incident를 최근 갱신 순으로 반환한다."""
    minutes = request.args.get("minutes", default=60, type=int)
    minutes = max(1, min(minutes or 60, 1440))
    client = get_client()

    try:
        response = client.search(
            index=ELASTIC_INCIDENT_INDEX,
            query={
                "range": {
                    "last_seen": {
                        "gte": f"now-{minutes}m",
                    }
                }
            },
            sort=[{"last_seen": "desc"}],
            size=200,
            ignore_unavailable=True,
        )
    except Exception:
        return jsonify({
            "status": "unavailable",
            "incidents": [],
        })

    incidents = []
    for hit in response.get("hits", {}).get("hits", []):
        incident = dict(hit.get("_source", {}))
        hosts = incident.get("affected_hosts") or []
        incident["hosts"] = hosts
        incident["host_count"] = len(hosts)
        incident["count"] = incident.get(
            "occurrence_count", 0
        )
        incident["recommendation"] = incident.get(
            "latest_recommendation"
        ) or {}
        incidents.append(incident)

    return jsonify({
        "status": "ready",
        "incidents": incidents,
    })


def _http_json(url: str) -> dict:
    try:
        with urlopen(url, timeout=2) as response:
            return json.load(response)
    except (OSError, URLError, ValueError) as exc:
        return {"error": str(exc)}


def _service_activity() -> dict[str, list[str]]:
    fluent = _http_json(
        "http://fluent-bit:2020/api/v1/metrics"
    )
    qdrant = _http_json(
        "http://qdrant:6333/collections/incident_cases"
    )
    elastic = _http_json(
        "http://elasticsearch:9200/_cluster/health"
    )
    return {
        "fluentbit_log": [
            "Fluent Bit metrics: "
            + json.dumps(fluent, ensure_ascii=False)
        ],
        "qdrant_log": [
            "Qdrant incident_cases: "
            + json.dumps(qdrant, ensure_ascii=False)
        ],
        "elasticsearch_log": [
            "Elasticsearch cluster: "
            + json.dumps(elastic, ensure_ascii=False)
        ],
    }


@log_generator_blueprint.get(
    "/api/v1/log-generator/activity"
)
def activity():
    return jsonify(_service_activity())
