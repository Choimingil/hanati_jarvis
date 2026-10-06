from datetime import datetime, UTC
import json
from flask import Blueprint, jsonify, request
from operations.queue import AnalysisQueue
from operations.redis_store import client
from operations.settings import FRESHNESS_SECONDS

metrics_blueprint = Blueprint("metrics", __name__)


@metrics_blueprint.post("/api/v1/metrics")
def ingest_metrics():
    payload = request.get_json(silent=True)
    required = {"timestamp", "host", "cpu", "memory", "disk", "network"}
    if (
        not isinstance(payload, dict)
        or not required.issubset(payload)
        or not isinstance(payload.get("host"), dict)
        or not payload["host"].get("hostname")
    ):
        return jsonify(
            status="invalid_request",
            reason="required metric fields and hostname missing",
            missing=sorted(
                required.difference(payload if isinstance(payload, dict) else {})
            ),
        ), 400
    try:
        stamp = datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError()
        age = (datetime.now(UTC) - stamp).total_seconds()
        if age < -30:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        return jsonify(
            status="invalid_request",
            reason="timezone-aware metric timestamp required; future data rejected",
        ), 400
    try:
        redis = client()
        job_id = AnalysisQueue(redis).enqueue("metrics", payload)
        redis.hset(
            "jarvis:metric-hosts",
            payload["host"]["hostname"],
            json.dumps(
                {
                    "timestamp": stamp.isoformat(),
                    "connections_access_denied": bool(
                        payload.get("network", {})
                        .get("connections", {})
                        .get("access_denied")
                    ),
                }
            ),
        )
        return jsonify(
            status="accepted", job_id=job_id, data_stale=age > FRESHNESS_SECONDS
        ), 202
    except Exception as exc:
        return jsonify(status="queue_unavailable", error=type(exc).__name__), 503
