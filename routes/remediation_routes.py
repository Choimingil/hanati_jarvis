import hashlib
import json
from datetime import UTC, datetime
from flask import Blueprint, jsonify, request
from config import ERROR_RULES
from dependencies import operational_incident_service, repository
from operations.execution import ExecutionCoordinator, TERMINAL
from operations.redis_store import client
from operations.privacy import redact
from operations.settings import bind_recommendation
from operations.incident_presentation import execution_summary, processing_summary
from utils.time_utils import now_iso

remediation_blueprint = Blueprint("remediation", __name__)


@remediation_blueprint.post("/api/v1/remediations/manual")
def register_manual_remediation():
    from aiops.manual_remediation_service import ManualRemediationService

    try:
        result = ManualRemediationService(repository).submit(request.get_json(silent=True))
        return jsonify(redact(result)), 200 if result["duplicate"] else 201
    except LookupError as exc:
        return jsonify(status="not_found", reason=str(exc)), 404
    except RuntimeError:
        return jsonify(status="blocked", reason="incident changed; reload details before registering"), 409
    except Exception as exc:
        return _error(exc)


def coordinator():
    return ExecutionCoordinator(client())


def _execution_id(body, decision):
    source = json.dumps(
        [
            body["incident_id"],
            body["recommendation_id"],
            body["action_id"],
            body.get("target") if decision == "approve" else None,
            decision,
        ],
        sort_keys=True,
    )
    return "EXEC-" + hashlib.sha256(source.encode()).hexdigest()[:24].upper()


def _validate_action_request(body):
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    for field in (
        "incident_id",
        "recommendation_id",
        "action_id",
        "incident_version",
        "approved_by",
    ):
        if not body.get(field):
            raise ValueError("missing " + field)
    if not isinstance(body["incident_version"], int) or isinstance(
        body["incident_version"], bool
    ):
        raise ValueError("incident_version must be an integer")
    if not all(
        isinstance(body[k], str) and 0 < len(body[k]) <= 200
        for k in ("incident_id", "recommendation_id", "action_id", "approved_by")
    ):
        raise ValueError("invalid action identifiers")
    incident = repository.get_operational_incident(body["incident_id"])
    recommendation = repository.get_recommendation(body["recommendation_id"])
    if not incident or not recommendation:
        raise ValueError("incident or recommendation not found")
    recommendation = bind_recommendation(incident, recommendation)
    simulation_actionable = (
        incident.get("synthetic") is True and incident.get("environment") == "simulation"
        and incident.get("status") == "INVESTIGATING" and bool(recommendation.get("targets"))
    )
    if incident.get("status") != "ACTION_REQUIRED" and not simulation_actionable:
        raise ValueError("incident is not actionable")
    if (
        recommendation.get("incident_id") != body["incident_id"]
        or incident.get("latest_recommendation_id") != body["recommendation_id"]
    ):
        raise ValueError("recommendation does not belong to incident")
    if (
        incident.get("version") != body["incident_version"]
        or recommendation.get("incident_version") != body["incident_version"]
    ):
        raise ValueError("stale recommendation")
    expiry = recommendation.get("expires_at")
    if not expiry or datetime.fromisoformat(
        expiry.replace("Z", "+00:00")
    ) < datetime.now(UTC):
        raise ValueError("expired recommendation")
    action = next(
        (
            a
            for a in recommendation.get("actions", [])
            if a.get("action_id") == body["action_id"]
        ),
        None,
    )
    code = incident.get("error_code")
    rule = ERROR_RULES.get(code, {})
    if not action or action.get("script_id") not in rule.get(
        "remediation_candidates", []
    ):
        raise ValueError("action not allowed for incident")
    return {
        "incident": incident,
        "recommendation": recommendation,
        "action": action,
        "script_id": action["script_id"],
        "error_code": code,
    }


def _error(exc):
    if isinstance(exc, (ValueError, TypeError)):
        return jsonify(status="blocked", reason=str(exc)), 409
    return jsonify(
        status="unavailable",
        reason="dependency unavailable; inspect service status",
        error=type(exc).__name__,
    ), 503


@remediation_blueprint.post("/api/v1/remediations/preflight")
def preflight():
    try:
        body = request.get_json(silent=True)
        context = _validate_action_request(body)
        result = coordinator().prepare(context, body.get("target"))
        return jsonify(result), 200 if result["status"] == "ready" else 409
    except Exception as exc:
        return _error(exc)


def _persist_result(manager, record):
    if record["result"].get("status") not in TERMINAL:
        return
    existing = repository.get_remediation_execution(record["execution_id"])
    if existing is None:
        repository.save_remediation_execution(
            redact(
                {k: v for k, v in record.items() if k not in {"locks", "agent_body"}}
            )
        )
    incident = repository.get_operational_incident(record["incident_id"])
    # Never overwrite another version or unrelated recommendation on reconciliation.
    if incident and incident.get("active_execution_id") == record["execution_id"]:
        operational_incident_service.transition(
            incident,
            "MONITORING"
            if record["result"]["status"] == "success"
            else "ACTION_REQUIRED",
            {"last_execution_id": record["execution_id"], "last_execution": execution_summary(record), "active_execution_id": None, "recovery_confirmation": "pending_execution"},
        )
    manager.release_host(record)


@remediation_blueprint.post("/api/v1/remediations/approve")
def approve_remediation():
    try:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        # Validate identifiers before consulting execution receipts.
        if not all(
            isinstance(body.get(k), str) and body[k]
            for k in ("incident_id", "recommendation_id", "action_id")
        ):
            raise ValueError("missing action identifiers")
        execution_id = _execution_id(body, "approve")
        manager = coordinator()
        record = manager.get(execution_id)
        if record:
            record = manager.reconcile(record)
            _persist_result(manager, record)
            return jsonify(
                {**record["result"], "execution_id": execution_id, "duplicate": True}
            ), 200
        context = _validate_action_request(body)
        # Approval is the only user step; inspect the selected target now.
        prepared = manager.prepare(context, body.get("target"))
        if prepared["status"] != "ready":
            return jsonify(prepared), 409
        # Analysis may update while the Agent is answering; validate again before locking.
        context = _validate_action_request(body)
        proof = manager.validate_proof(
            {**body, "preflight_id": prepared["preflight_id"]}, context
        )
        record, new = manager.reserve(execution_id, body, context, proof)
        if new:
            operational_incident_service.transition(
                context["incident"],
                "REMEDIATING",
                {"active_execution_id": execution_id},
            )
            record = manager.dispatch(record)
        _persist_result(manager, record)
        return jsonify(
            {**record["result"], "execution_id": execution_id}
        ), 200 if record["result"].get("status") == "success" else 409
    except Exception as exc:
        return _error(exc)


@remediation_blueprint.get("/api/v1/remediations/executions/<execution_id>")
def execution_status(execution_id):
    try:
        manager = coordinator()
        record = manager.get(execution_id)
        if not record:
            return jsonify(status="not_found"), 404
        record = manager.reconcile(record)
        _persist_result(manager, record)
        return jsonify(
            {
                "execution_id": execution_id,
                "target": record["target"],
                "result": record["result"],
            }
        )
    except Exception as exc:
        return _error(exc)


@remediation_blueprint.post("/api/v1/remediations/reject")
def reject_remediation():
    try:
        body = request.get_json(silent=True)
        context = _validate_action_request(body)
        execution_id = _execution_id(body, "reject")
        if repository.get_remediation_execution(execution_id):
            return jsonify(status="already_processed")
        coordinator().reject(execution_id, body)
        result = {"status": "rejected", "reason": redact(body.get("reason", ""))}
        repository.save_remediation_execution(
            {
                "execution_id": execution_id,
                "incident_id": body["incident_id"],
                "recommendation_id": body["recommendation_id"],
                "action_id": body["action_id"],
                "script_id": context["script_id"],
                "approved_by": redact(body["approved_by"]),
                "approved_at": now_iso(),
                "result": result,
            }
        )
        return jsonify(result)
    except Exception as exc:
        return _error(exc)


@remediation_blueprint.post("/api/v1/remediations/diagnose")
def request_diagnosis():
    try:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        context = _validate_action_request(body)
        target = body.get("target")
        if target not in context["action"].get("targets", []):
            raise ValueError("target not bound to recommendation")
        results = [
            coordinator().diagnose(target, script_id)
            for script_id in ERROR_RULES[context["error_code"]].get(
                "diagnostic_scripts", []
            )
        ]
        return jsonify(status="completed", diagnosis_results=results)
    except Exception as exc:
        return _error(exc)


@remediation_blueprint.post("/api/v1/remediations/verify")
def verify_remediation():
    try:
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not body.get("execution_id"):
            raise ValueError("execution_id required")
        manager = coordinator()
        record = manager.get(body["execution_id"])
        if not record or record["result"].get("status") != "success":
            raise ValueError("successful execution required")
        result = manager.verify(record)
        result["incident_id"] = record["incident_id"]
        repository.save_recovery_verification(redact(result))
        if result.get("recovered"):
            record["recovery_verified"] = True
            manager.redis.set(
                "jarvis:execution:" + record["execution_id"], json.dumps(record)
            )
            manager.release_host(record)
        incident = repository.get_operational_incident(record["incident_id"])
        if (
            result.get("recovered")
            and incident
            and incident.get("status") == "MONITORING"
            and incident.get("last_execution_id") == record["execution_id"]
        ):
            incident = operational_incident_service.transition(
                incident, "RESOLVED", {"recovered_at": now_iso(), "recovery_confirmation": result.get("execution_mode", "business_probe")}
            )
        if incident:
            result["incident"] = incident
            result["processing"] = processing_summary(incident)
        return jsonify(redact(result))
    except Exception as exc:
        return _error(exc)
