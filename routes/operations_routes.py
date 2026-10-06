from flask import Blueprint, jsonify
from operations.health import service_status
from operations.queue import AnalysisQueue
from operations.redis_store import client

operations_blueprint = Blueprint("operations", __name__)


@operations_blueprint.get("/api/v1/operations/status")
def status():
    return jsonify(service_status())


@operations_blueprint.get("/api/v1/analysis/jobs/<job_id>")
def job_status(job_id):
    if len(job_id) != 32 or not all(c in "0123456789abcdef" for c in job_id):
        return jsonify(status="invalid_request"), 400
    try:
        job = AnalysisQueue(client()).get(job_id)
        return (jsonify(job), 200) if job else (jsonify(status="not_found"), 404)
    except Exception as exc:
        return jsonify(status="unavailable", error=type(exc).__name__), 503
