import hashlib
import threading
from datetime import UTC, datetime

from flask import Blueprint, jsonify, request

from config import (
    DIAGNOSTIC_SCRIPTS,
    ERROR_RULES,
    REMEDIATION_SCRIPTS,
)
from dependencies import (
    operational_incident_service,
    recovery_verifier,
    repository,
)
from script_runner import run_script
from utils.time_utils import now_iso


remediation_blueprint = Blueprint(
    "remediation",
    __name__,
)

# 한 추천의 조치 제안 중 하나만 실행되도록, 실행 중인 추천 id를 잡아둔다
# (저장 이력만 보면 동시에 들어온 두 승인 요청을 둘 다 통과시킬 수 있다).
_approving_recommendations: set[str] = set()
_approving_lock = threading.Lock()


def _approved_execution(recommendation_id: str) -> dict | None:
    """이 추천에서 이미 승인(실행)된 조치가 있으면 그 이력을 반환한다."""
    for execution in repository.find_remediation_executions(
        recommendation_id
    ):
        if (execution.get("result") or {}).get("status") != "rejected":
            return execution
    return None


def _execution_id(body: dict, decision: str) -> str:
    source = "|".join([
        body["incident_id"],
        body["recommendation_id"],
        body["action_id"],
        decision,
    ])
    return "EXEC-" + hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()[:16].upper()


def _validate_action_request(body):
    if not isinstance(body, dict):
        return None, ({
            "status": "invalid_request",
            "reason": "JSON object is required",
        }, 400)

    required = [
        "incident_id",
        "recommendation_id",
        "action_id",
        "incident_version",
        "approved_by",
    ]
    missing = [field for field in required if body.get(field) is None]
    if missing:
        return None, ({
            "status": "invalid_request",
            "missing_fields": missing,
        }, 400)

    incident = repository.get_operational_incident(
        body["incident_id"]
    )
    if incident is None:
        return None, ({
            "status": "not_found",
            "reason": "incident not found",
        }, 404)
    if incident.get("status") not in {
        "ACTION_REQUIRED", "REMEDIATING"
    }:
        return None, ({
            "status": "blocked",
            "reason": "incident is not actionable",
            "incident_status": incident.get("status"),
        }, 409)

    recommendation = repository.get_recommendation(
        body["recommendation_id"]
    )
    if recommendation is None:
        return None, ({
            "status": "not_found",
            "reason": "recommendation not found",
        }, 404)
    if (
        recommendation.get("incident_id") != body["incident_id"]
        or incident.get("latest_recommendation_id")
        != body["recommendation_id"]
    ):
        return None, ({
            "status": "blocked",
            "reason": "recommendation does not belong to incident",
        }, 409)

    expected = int(body["incident_version"])
    if (
        int(incident.get("version", 0)) != expected
        or int(recommendation.get("incident_version", 0)) != expected
    ):
        return None, ({
            "status": "stale_recommendation",
            "current_version": incident.get("version"),
        }, 409)

    expires_at = recommendation.get("expires_at")
    if expires_at:
        expiry = datetime.fromisoformat(
            expires_at.replace("Z", "+00:00")
        )
        if expiry < datetime.now(UTC):
            return None, ({
                "status": "expired_recommendation",
                "reason": "runbook recommendation expired",
            }, 409)

    action = next((
        item for item in recommendation.get("actions", [])
        if item.get("action_id") == body["action_id"]
    ), None)
    if action is None:
        return None, ({
            "status": "blocked",
            "reason": "action is not part of recommendation",
        }, 403)

    script_id = action.get("script_id")
    error_code = incident.get("error_code")
    rule = ERROR_RULES.get(error_code)
    if (
        rule is None
        or script_id not in rule.get("remediation_candidates", [])
    ):
        return None, ({
            "status": "blocked",
            "reason": "script is not allowed for incident",
        }, 403)

    return {
        "incident": incident,
        "recommendation": recommendation,
        "action": action,
        "script_id": script_id,
        "error_code": error_code,
    }, None


@remediation_blueprint.post("/api/v1/remediations/approve")
def approve_remediation():
    body = request.get_json(silent=True)
    execution_id = (
        _execution_id(body, "approve")
        if isinstance(body, dict) and all(
            body.get(key) is not None
            for key in (
                "incident_id",
                "recommendation_id",
                "action_id",
            )
        )
        else None
    )
    existing = (
        repository.get_remediation_execution(execution_id)
        if execution_id else None
    )
    if existing is not None:
        return jsonify({
            **existing.get("result", {}),
            "execution_id": execution_id,
            "status": "already_processed",
        })

    context, error = _validate_action_request(body)
    if error is not None:
        return jsonify(error[0]), error[1]
    execution_id = _execution_id(body, "approve")
    recommendation_id = body["recommendation_id"]

    with _approving_lock:
        if recommendation_id in _approving_recommendations:
            return jsonify({
                "status": "blocked",
                "reason": "another action is running "
                          "for this recommendation",
            }), 409
        approved = _approved_execution(recommendation_id)
        if approved is not None:
            return jsonify({
                "status": "blocked",
                "reason": "another action was already approved "
                          "for this recommendation",
                "approved_action_id": approved.get("action_id"),
                "approved_script_id": approved.get("script_id"),
            }), 409
        _approving_recommendations.add(recommendation_id)

    try:
        return _run_approved_action(body, context, execution_id)
    finally:
        with _approving_lock:
            _approving_recommendations.discard(recommendation_id)


def _run_approved_action(body, context, execution_id):
    incident = operational_incident_service.transition(
        context["incident"],
        "REMEDIATING",
        {"active_execution_id": execution_id},
    )
    result = run_script(
        context["script_id"],
        REMEDIATION_SCRIPTS,
    )
    execution = {
        "execution_id": execution_id,
        "incident_id": body["incident_id"],
        "recommendation_id": body["recommendation_id"],
        "action_id": body["action_id"],
        "script_id": context["script_id"],
        "error_code": context["error_code"],
        "approved_by": body["approved_by"],
        "approved_at": now_iso(),
        "result": result,
    }
    repository.save_remediation_execution(execution)

    next_status = (
        "MONITORING"
        if result.get("status") == "success"
        else "ACTION_REQUIRED"
    )
    operational_incident_service.transition(
        incident,
        next_status,
        {
            "last_execution_id": execution_id,
            "active_execution_id": None,
        },
    )
    status_code = 200 if result.get("status") == "success" else 400
    return jsonify({
        **result,
        "execution_id": execution_id,
        "incident_status": next_status,
    }), status_code


@remediation_blueprint.post("/api/v1/remediations/reject")
def reject_remediation():
    body = request.get_json(silent=True)
    execution_id = (
        _execution_id(body, "reject")
        if isinstance(body, dict) and all(
            body.get(key) is not None
            for key in (
                "incident_id",
                "recommendation_id",
                "action_id",
            )
        )
        else None
    )
    existing = (
        repository.get_remediation_execution(execution_id)
        if execution_id else None
    )
    if existing is not None:
        return jsonify({
            **existing.get("result", {}),
            "execution_id": execution_id,
            "status": "already_processed",
        })

    context, error = _validate_action_request(body)
    if error is not None:
        return jsonify(error[0]), error[1]
    execution_id = _execution_id(body, "reject")

    result = {
        "script_id": context["script_id"],
        "status": "rejected",
        "reason": body.get("reason", ""),
    }
    repository.save_remediation_execution({
        "execution_id": execution_id,
        "incident_id": body["incident_id"],
        "recommendation_id": body["recommendation_id"],
        "action_id": body["action_id"],
        "script_id": context["script_id"],
        "error_code": context["error_code"],
        "approved_by": body["approved_by"],
        "approved_at": now_iso(),
        "result": result,
    })
    return jsonify({
        **result,
        "execution_id": execution_id,
    })


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


@remediation_blueprint.post("/api/v1/remediations/verify")
def verify_remediation():
    body = request.get_json(silent=True) or {}
    incident_id = body.get("incident_id")
    if not incident_id:
        return jsonify({
            "status": "invalid_request",
            "missing_fields": ["incident_id"],
        }), 400

    incident = repository.get_incident(incident_id)
    if incident is None:
        return jsonify({
            "status": "not_found",
            "incident_id": incident_id,
        }), 404

    snapshots = repository.recent_metrics(
        incident.get("host", "unknown"), minutes=5
    )
    verification = recovery_verifier.verify(incident, snapshots)
    verification["verified_at"] = now_iso()
    repository.save_recovery_verification(verification)
    return jsonify(verification)
