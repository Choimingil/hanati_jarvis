"""웹 콘솔의 "분석" 버튼이 log_generator/main.py와 같은 방식(시나리오
실행 -> fluentbit가 tail하는 파일에 기록)으로 동작하도록 하는 라우트.

실제 탐지/진단/추천은 fluent-bit가 파일을 tail해서 POST /api/v1/logs로
전달한 뒤 비동기로 이뤄지므로, 이 블루프린트는 (1) 시나리오를 트리거하고
(2) Elasticsearch에 쌓인 추천 결과 중 가장 최근 것을 폴링해서 보여주는
두 엔드포인트로 구성된다.
"""

import sys
from pathlib import Path

from flask import Blueprint, jsonify, request

from config import ELASTIC_RECOMMENDATION_INDEX
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
                "match": {
                    "recommendation.error_code": error_code
                }
            },
            size=20,
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
        "recommendation": latest["recommendation"],
    })
