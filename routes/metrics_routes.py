from flask import Blueprint, jsonify, request

from dependencies import metric_analysis_service, repository


metrics_blueprint = Blueprint("metrics", __name__)


@metrics_blueprint.post("/api/v1/metrics")
def ingest_metrics():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "invalid_request",
            "message": "JSON object is required",
        }), 400

    required = {"timestamp", "host", "cpu", "memory", "disk", "network"}
    missing = sorted(required.difference(payload))
    if missing:
        return jsonify({
            "status": "invalid_request",
            "message": "required fields are missing",
            "missing": missing,
        }), 400

    try:
        repository.save_metric(payload)
    except Exception as exc:
        return jsonify({
            "status": "storage_failed",
            "message": str(exc),
        }), 503

    try:
        analysis = metric_analysis_service.analyze(payload)
    except Exception as exc:
        return jsonify({
            "status": "stored",
            "analysis_status": "failed",
            "analysis_error": str(exc),
        }), 201

    return jsonify({
        "status": "stored",
        "analysis_status": "completed",
        "detections": analysis,
    }), 201
