"""웹 콘솔의 "분석" 버튼이 log_generator/main.py와 같은 방식(시나리오
실행 -> fluentbit가 tail하는 파일에 기록)으로 동작하도록 하는 라우트.

실제 탐지/진단/추천은 fluent-bit가 파일을 tail해서 POST /api/v1/logs로
전달한 뒤 비동기로 이뤄진다. 시나리오 시작은 Redis로 즉시 공유하고,
장애 목록·상세와 Elasticsearch의 분석 결과를 별도로 조회한다.
"""

import json
import sys
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request

from config import (
    CASE_SEARCHER_BACKEND,
    ELASTIC_DIAGNOSIS_INDEX,
    ELASTIC_LOG_INDEX,
    ELASTIC_RECOMMENDATION_INDEX,
    QDRANT_COLLECTION,
)
from dependencies import repository
from elastic.client import get_client
from utils.time_utils import now_iso
from operations.privacy import redact
from operations.redis_store import client as redis_client
from operations.activity import redis_activity, worker_activity

LOG_GENERATOR_DIR = Path(__file__).resolve().parent.parent / "log_generator"
if str(LOG_GENERATOR_DIR) not in sys.path:
    sys.path.insert(0, str(LOG_GENERATOR_DIR))

from registry import SCENARIO_REGISTRY  # noqa: E402
from trigger import run_scenario  # noqa: E402


log_generator_blueprint = Blueprint("log_generator", __name__)

# Publish before generation so clients can follow logs while the request is running.
# Redis shares this state across API processes; expire it with the 10-minute view.
LATEST_RUN_KEY = "jarvis:log-generator:latest-run"
LATEST_RUN_TTL = 600


def _finish_run(run, phase):
    # An older request completing must not overwrite a newer admin's run.
    updated = {**run, "phase": phase}
    redis_client().eval(
        "local current=redis.call('GET', KEYS[1]); "
        "if current and cjson.decode(current).run_id == ARGV[1] then "
        "return redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3]); end; return 0;",
        1, LATEST_RUN_KEY, run["run_id"], json.dumps(updated), LATEST_RUN_TTL,
    )


@log_generator_blueprint.get("/api/v1/log-generator/scenarios")
def list_scenarios():
    return jsonify(
        [
            {"key": key, "label": label}
            for key, (_, label, _) in SCENARIO_REGISTRY.items()
        ]
    )


@log_generator_blueprint.post("/api/v1/log-generator/run")
def run():
    body = request.get_json(silent=True) or {}
    key = body.get("scenario")

    if key not in SCENARIO_REGISTRY:
        return jsonify(
            {
                "status": "invalid_request",
                "reason": "unknown scenario",
            }
        ), 400

    triggered_at = now_iso()
    current_run = {
        "run_id": uuid.uuid4().hex,
        "scenario": key,
        "label": SCENARIO_REGISTRY[key][1],
        "triggered_at": triggered_at,
        "error_code": SCENARIO_REGISTRY[key][2],
        "phase": "running",
    }
    try:
        redis_client().set(LATEST_RUN_KEY, json.dumps(current_run), ex=LATEST_RUN_TTL)
    except Exception as exc:
        return jsonify(
            status="unavailable", reason="scenario synchronization unavailable",
            error=type(exc).__name__,
        ), 503
    try:
        result = run_scenario(key)
    except Exception as exc:
        try:
            _finish_run(current_run, "failed")
        except Exception:
            pass
        return jsonify(
            status="failed", reason="scenario generation failed",
            error=type(exc).__name__,
        ), 503
    try:
        _finish_run(current_run, "completed")
    except Exception as exc:
        return jsonify(
            status="unavailable",
            reason="scenario generated but synchronization update failed",
            error=type(exc).__name__,
        ), 503

    return jsonify(
        {
            "status": "triggered",
            "run_id": current_run["run_id"],
            "triggered_at": triggered_at,
            "error_code": result["error_code"],
            "events": result["events"],
        }
    )


@log_generator_blueprint.get("/api/v1/log-generator/latest-run")
def latest_run():
    try:
        stored = redis_client().get(LATEST_RUN_KEY)
        run = json.loads(stored) if stored else None
    except Exception as exc:
        return jsonify(status="unavailable", error=type(exc).__name__), 503
    if run is None:
        return jsonify({"status": "none"})
    return jsonify({"status": "ready", "run": run})


@log_generator_blueprint.get("/api/v1/log-generator/latest-recommendation")
def latest_recommendation():
    error_code = request.args.get("error_code")
    since = request.args.get("since")

    if not error_code or not since:
        return jsonify(
            {
                "status": "invalid_request",
            }
        ), 400

    client = get_client()

    try:
        response = client.search(
            index=ELASTIC_RECOMMENDATION_INDEX,
            query={
                "bool": {
                    "should": [
                        {"match": {"recommendation.error_code": error_code}},
                        {"match": {"guidance.original_error_code": error_code}},
                    ],
                    "minimum_should_match": 1,
                    # 같은 에러코드 추천이 누적되므로 시간 조건·정렬 없이
                    # size만 두면 오래된 문서만 잡혀 최신 추천을 놓친다.
                    "filter": [
                        {"range": {"timestamp": {"gt": since}}},
                    ],
                }
            },
            sort=[{"timestamp": "desc"}],
            size=20,
            # 첫 추천이 저장되기 전엔 이 인덱스가 아직 없다 - 없어도
            # 404 대신 빈 결과로 받아서 폴링 중 정상 상태로 취급한다.
            ignore_unavailable=True,
        )
    except Exception:
        return jsonify({"status": "pending"})

    hits = response["hits"]["hits"]
    fresh = [
        hit["_source"] for hit in hits if hit["_source"].get("timestamp", "") > since
    ]

    if not fresh:
        return jsonify({"status": "pending"})

    latest = max(fresh, key=lambda doc: doc["timestamp"])
    recommendation = latest.get("recommendation") or latest.get("guidance")

    return jsonify(
        {
            "status": "ready",
            "recommendation": recommendation,
            "decisions": _safe_decisions(
                (recommendation or {}).get("recommendation_id")
            ),
        }
    )


def _safe_decisions(recommendation_id: str | None) -> list[dict]:
    """추천에 대해 이미 내려진 승인/거부 이력.

    새로고침해도 화면이 처리 완료 상태를 복원할 수 있도록 함께 내려준다.
    """
    if not recommendation_id:
        return []

    decisions = []
    for doc in repository.find_remediation_executions(recommendation_id):
        result = doc.get("result") or {}
        decisions.append(
            {
                "action_id": doc.get("action_id"),
                "script_id": doc.get("script_id"),
                "decision": (
                    "reject" if result.get("status") == "rejected" else "approve"
                ),
                "approved_by": doc.get("approved_by"),
                "approved_at": doc.get("approved_at"),
                "result": result,
            }
        )
    return decisions


@log_generator_blueprint.get("/api/v1/log-generator/incidents")
def recent_incidents():
    """영속화된 운영 Incident를 최근 갱신 순으로 반환한다."""
    minutes = request.args.get("minutes", default=10, type=int)
    minutes = max(1, min(minutes or 10, 1440))
    try:
        documents = repository.list_operational_incidents(minutes)
    except Exception as exc:
        return jsonify(
            status="unavailable", incidents=[], error=type(exc).__name__
        ), 503

    incidents = []
    for document in documents:
        incident = dict(document)
        hosts = incident.get("affected_hosts") or []
        incident["hosts"] = hosts
        incident["host_count"] = len(hosts)
        incident["count"] = incident.get("occurrence_count", 0)
        incident["recommendation"] = incident.get("latest_recommendation") or {}
        incidents.append(incident)

    incidents.sort(
        key=lambda i: (i.get("status") == "RESOLVED", i.get("priority_rank", 3))
    )
    return jsonify(
        {
            "status": "ready",
            "incidents": incidents,
            "server_time": now_iso(),
        }
    )


@log_generator_blueprint.get("/api/v1/log-generator/incidents/<incident_id>")
def incident_detail(incident_id):
    """선택한 장애의 최신 상태와 해당 장애에 속하는 최근 로그를 반환한다."""
    try:
        incident = repository.get_operational_incident(incident_id)
        if incident is None:
            return jsonify(status="not_found"), 404
    except Exception as exc:
        return jsonify(status="unavailable", error=type(exc).__name__), 503

    try:
        logs = repository.recent_incident_logs(incident_id, minutes=10)
        logs_status = "ready"
    except Exception:
        logs, logs_status = [], "unavailable"
    return jsonify(redact({
        "status": "ready", "incident": incident,
        "logs": logs, "logs_status": logs_status,
    }))


def _format_time(value: str | None) -> str:
    # "2026-09-17T20:06:58.949576+09:00" -> "20:06:58"
    return (value or "")[11:19]


def _es_since(
    index: str,
    time_field: str,
    since: str | None,
    size: int = 60,
) -> list[dict]:
    """이번 트리거 이후 index에 저장된 문서를 오래된 순으로 가져온다.

    since가 없으면(콘솔 첫 진입) 최근 5분으로 스코프를 좁힌다.
    """
    response = get_client().search(
        index=index,
        query={"range": {time_field: {"gte": since or "now-5m"}}},
        sort=[
            {
                time_field: {
                    "order": "desc",
                    "unmapped_type": "date",
                }
            }
        ],
        size=size,
        ignore_unavailable=True,
    )
    hits = [hit["_source"] for hit in response["hits"]["hits"]]
    return list(reversed(hits))


def _received_logs(since: str | None) -> list[str]:
    # fluent-bit가 POST /api/v1/logs로 넘긴 로그는 레벨과 무관하게
    # 전부 application-logs에 저장된다 -> "aiops가 실제로 받은 것".
    return [
        f"{_format_time(doc.get('received_at'))} "
        f"[{doc.get('level')}] {doc.get('host')} "
        f"{doc.get('message')}"
        + (f"  (incident={doc['incident_id']})" if doc.get("incident_id") else "")
        for doc in _es_since(ELASTIC_LOG_INDEX, "received_at", since)
    ]


def _stored_analysis(since: str | None) -> list[str]:
    lines = [
        f"{_format_time(doc.get('timestamp'))} [진단] "
        f"{doc.get('error_code')} {doc.get('script_id')} "
        f"-> {(doc.get('result') or {}).get('status', '')}"
        for doc in _es_since(ELASTIC_DIAGNOSIS_INDEX, "timestamp", since, size=30)
    ]
    for doc in _es_since(ELASTIC_RECOMMENDATION_INDEX, "timestamp", since, size=30):
        if doc.get("guidance"):
            guidance = doc["guidance"]
            lines.append(
                f"{_format_time(doc.get('timestamp'))} [리소스 가이드] "
                f"{guidance.get('guidance_id')} "
                f"(원 에러코드={guidance.get('original_error_code')})"
            )
        else:
            recommendation = doc.get("recommendation") or {}
            lines.append(
                f"{_format_time(doc.get('timestamp'))} [추천] "
                f"{recommendation.get('error_code')} "
                f"source={doc.get('source', 'log')}"
            )
    return sorted(lines)


def _qdrant_status() -> list[str]:
    from qdrant.client import get_client as get_qdrant_client

    info = get_qdrant_client().get_collection(QDRANT_COLLECTION)
    return [
        f"collection={QDRANT_COLLECTION} "
        f"points={info.points_count} status={info.status}",
        f"과거 사례 검색 backend={CASE_SEARCHER_BACKEND}"
        + (
            " (로그 분석은 Elasticsearch로 검색 - Qdrant는 메트릭 이상 탐지/"
            "운영자 피드백 저장 시에만 쓰임)"
            if CASE_SEARCHER_BACKEND == "elastic"
            else ""
        ),
    ]


def _safe(source: str, fetch) -> list[str]:
    # 한 저장소가 죽어도 나머지 패널은 보여야 하고, 빈 목록 대신
    # 원인을 보여줘야 "데이터가 없는 것"과 구분된다.
    try:
        return fetch()
    except Exception as error:
        return [f"{source} 조회 실패: {redact(str(error))}"]


@log_generator_blueprint.get("/api/v1/log-generator/activity")
def activity():
    since = request.args.get("since")

    return jsonify(
        {
            "fluentbit_log": _safe("Elasticsearch", lambda: _received_logs(since)),
            "qdrant_log": _safe("Qdrant", _qdrant_status),
            "elasticsearch_log": _safe(
                "Elasticsearch", lambda: _stored_analysis(since)
            ),
            "redis_log": _safe("Redis", lambda: redis_activity(redis_client(), since)),
            "worker_log": _safe("Worker", lambda: worker_activity(redis_client(), since)),
        }
    )
