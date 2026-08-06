from flask import Blueprint, jsonify, request

from config import (
    DIAGNOSTIC_SCRIPTS,
    ERROR_RULES,
    REMEDIATION_SCRIPTS,
)
from dependencies import repository
from script_runner import run_script
from utils.time_utils import now_iso


remediation_blueprint = Blueprint(
    "remediation",
    __name__,
)


def _validate_runbook_request(body):
    """approve/reject 공통 검증: script_id가 해당 error_code의 Runbook
    (remediation_candidates)에 실제 속하는지 확인한다.
    통과하면 None, 아니면 (jsonify 응답, status_code) 튜플을 돌려준다."""
    if not isinstance(body, dict):
        return {
            "status": "invalid_request",
            "reason": "JSON object is required",
        }, 400

    required_fields = ["script_id", "error_code", "approved_by"]
    missing_fields = [
        field for field in required_fields if not body.get(field)
    ]

    if missing_fields:
        return {
            "status": "invalid_request",
            "missing_fields": missing_fields,
        }, 400

    error_code = body["error_code"]
    script_id = body["script_id"]
    rule = ERROR_RULES.get(error_code)

    if rule is None:
        return {
            "status": "blocked",
            "reason": "unknown error code",
            "error_code": error_code,
        }, 400

    allowed_candidates = rule.get("remediation_candidates", [])

    if script_id not in allowed_candidates:
        return {
            "status": "blocked",
            "reason": (
                "script is not an allowed remediation "
                "runbook for this error code"
            ),
            "error_code": error_code,
            "script_id": script_id,
        }, 403

    return None


@remediation_blueprint.route(
    "/api/v1/remediations/approve",
    methods=["POST"],
)
def approve_remediation():
    body = request.get_json(silent=True)
    error = _validate_runbook_request(body)
    if error is not None:
        return jsonify(error[0]), error[1]

    script_id = body["script_id"]
    error_code = body["error_code"]
    approved_by = body["approved_by"]

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


@remediation_blueprint.route(
    "/api/v1/remediations/reject",
    methods=["POST"],
)
def reject_remediation():
    body = request.get_json(silent=True)
    error = _validate_runbook_request(body)
    if error is not None:
        return jsonify(error[0]), error[1]

    script_id = body["script_id"]
    error_code = body["error_code"]
    approved_by = body["approved_by"]
    reason = body.get("reason", "")

    result = {
        "script_id": script_id,
        "status": "rejected",
        "reason": reason,
    }

    repository.save_remediation({
        "timestamp": now_iso(),
        "error_code": error_code,
        "script_id": script_id,
        "approved_by": approved_by,
        "result": result,
    })

    return jsonify(result)


@remediation_blueprint.route(
    "/api/v1/remediations/diagnose",
    methods=["POST"],
)
def request_diagnosis():
    """"진단 요청" 버튼: Runbook을 실행하지 않고, 그 Runbook이 속한
    error_code의 진단 스크립트를 다시 돌려서 최신 상태를 보여준다."""
    body = request.get_json(silent=True) or {}
    error_code = body.get("error_code")

    if not error_code:
        return jsonify({
            "status": "invalid_request",
            "missing_fields": ["error_code"],
        }), 400

    rule = ERROR_RULES.get(error_code)

    if rule is None:
        return jsonify({
            "status": "blocked",
            "reason": "unknown error code",
            "error_code": error_code,
        }), 400

    diagnosis_results = [
        run_script(script_id, DIAGNOSTIC_SCRIPTS)
        for script_id in rule.get("diagnostic_scripts", [])
    ]

    return jsonify({
        "status": "ok",
        "error_code": error_code,
        "diagnosis_results": diagnosis_results,
    })
