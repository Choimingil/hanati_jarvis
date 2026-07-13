from flask import Blueprint, jsonify, request

from config import ERROR_RULES, REMEDIATION_SCRIPTS
from dependencies import repository
from script_runner import run_script
from utils.time_utils import now_iso


remediation_blueprint = Blueprint(
    "remediation",
    __name__,
)


@remediation_blueprint.route(
    "/api/v1/remediations/approve",
    methods=["POST"],
)
def approve_remediation():
    body = request.get_json(silent=True)

    if not isinstance(body, dict):
        return jsonify({
            "status": "invalid_request",
            "reason": "JSON object is required",
        }), 400

    required_fields = [
        "script_id",
        "error_code",
        "approved_by",
    ]

    missing_fields = [
        field
        for field in required_fields
        if not body.get(field)
    ]

    if missing_fields:
        return jsonify({
            "status": "invalid_request",
            "missing_fields": missing_fields,
        }), 400

    script_id = body["script_id"]
    error_code = body["error_code"]
    approved_by = body["approved_by"]

    rule = ERROR_RULES.get(error_code)

    if rule is None:
        return jsonify({
            "status": "blocked",
            "reason": "unknown error code",
            "error_code": error_code,
        }), 400

    allowed_candidates = rule.get(
        "remediation_candidates",
        [],
    )

    if script_id not in allowed_candidates:
        return jsonify({
            "status": "blocked",
            "reason": (
                "script is not an allowed remediation "
                "for this error code"
            ),
            "error_code": error_code,
            "script_id": script_id,
        }), 403

    result = run_script(
        script_id,
        REMEDIATION_SCRIPTS,
    )

    repository.save_remediation({
        "timestamp": now_iso(),
        "error_code": error_code,
        "script_id": script_id,
        "approved_by": approved_by,
        "result": result,
    })

    status_code = (
        200
        if result["status"] == "success"
        else 400
    )

    return jsonify(result), status_code
