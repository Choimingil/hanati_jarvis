from flask import Blueprint, jsonify, request

from dependencies import operator_feedback_service


guidance_blueprint = Blueprint("guidance", __name__)


@guidance_blueprint.post("/api/v1/guidance/feedback")
def submit_guidance_feedback():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({
            "status": "invalid_request",
            "reason": "JSON object is required",
        }), 400
    missing = [
        field for field in ("guidance_id", "operator", "verdict")
        if not body.get(field)
    ]
    if missing:
        return jsonify({
            "status": "invalid_request",
            "missing_fields": missing,
        }), 400
    try:
        result = operator_feedback_service.submit(body)
    except LookupError as exc:
        return jsonify({"status": "not_found", "reason": str(exc)}), 404
    except ValueError as exc:
        return jsonify({
            "status": "invalid_request", "reason": str(exc)
        }), 400
    return jsonify(result), 201
