from flask import Blueprint, jsonify, request
from operations.queue import AnalysisQueue
from operations.redis_store import client

log_blueprint = Blueprint("logs", __name__)


@log_blueprint.post("/api/v1/logs")
def receive_logs():
    payload = request.get_json(silent=True)
    logs = [payload] if isinstance(payload, dict) else payload
    if (
        not isinstance(logs, list)
        or not logs
        or len(logs) > 100
        or not all(isinstance(log, dict) for log in logs)
    ):
        return jsonify(
            status="invalid_request", reason="one object or 1..100 objects required"
        ), 400
    try:
        # Redis MULTI per receipt; a retry can deliver duplicates, which analysis
        # handles at least once. Fluent Bit receives compact IDs, not LLM output.
        queue = AnalysisQueue(client())
        ids = queue.enqueue_many("logs", logs)
        return jsonify(status="accepted", job_ids=ids), 202
    except Exception as exc:
        return jsonify(status="queue_unavailable", error=type(exc).__name__), 503
