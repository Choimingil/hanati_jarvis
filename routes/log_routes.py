from typing import Any

from flask import Blueprint, jsonify, request

from dependencies import log_processor


log_blueprint = Blueprint(
    "logs",
    __name__,
)


@log_blueprint.post("/api/v1/logs")
def receive_logs():
    payload = request.get_json(silent=True)

    if payload is None:
        return jsonify({
            "status": "invalid_request",
            "reason": "JSON body is required",
        }), 400

    if isinstance(payload, dict):
        logs = [payload]
    elif isinstance(payload, list):
        logs = payload
    else:
        return jsonify({
            "status": "invalid_request",
            "reason": (
                "body must be a JSON object or array"
            ),
        }), 400

    responses: list[dict[str, Any]] = []

    for raw_log in logs:
        if not isinstance(raw_log, dict):
            responses.append({
                "status": "invalid_log",
            })
            continue

        try:
            result = log_processor.process(
                raw_log
            )
            responses.append(result)

        except Exception as exc:
            responses.append({
                "status": "processing_failed",
                "reason": str(exc),
            })

    return jsonify(responses), 200
