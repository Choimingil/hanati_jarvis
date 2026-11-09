"""결재(승인 요청)·보류(킵)·에러별 예외 처리 규칙·알림 API.

조치 흐름: 운영자 "결재 요청" → admin "결재 승인" → 기존 승인 실행 경로(검증·잠금·실행)
→ 복구 확인. 결재 승인 시점의 최신 추천과 장애 버전으로 다시 검증한다.
"""

from flask import Blueprint, jsonify, request

from dependencies import operational_incident_service, repository
from operations.incident_history import similar_history
from operations.incident_workflow import WorkflowStore
from operations.privacy import redact
from operations.settings import bind_recommendation

workflow_blueprint = Blueprint("workflow", __name__)

ACTIONABLE_ERRORS = {
    "stale recommendation", "expired recommendation", "incident is not actionable",
    "recommendation does not belong to incident", "action not allowed for incident",
}


@workflow_blueprint.after_request
def no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


def _text(body, field, limit=200, required=True):
    value = body.get(field) if isinstance(body, dict) else None
    if value is None and not required:
        return ""
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("invalid " + field)
    return value.strip()


def _blocked(reason, status=409, **extra):
    return jsonify(status="blocked", reason=reason, **extra), status


# --------------------------------------------------------------------- 결재
@workflow_blueprint.post("/api/v1/approvals")
def request_approval():
    """Runbook의 '결재 요청'. 조치는 실행하지 않고 결재 대기열에 올린다."""
    from routes.remediation_routes import _validate_action_request

    try:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        requested_by = _text(body, "requested_by")
        comment = _text(body, "comment", limit=1000, required=False)
        context = _validate_action_request({**body, "approved_by": requested_by})
        target = body.get("target")
        if target not in context["action"].get("targets", []):
            raise ValueError("target not bound to recommendation")
        incident = context["incident"]
        approval, created = WorkflowStore().create_approval({
            "incident_id": incident["incident_id"], "recommendation_id": body["recommendation_id"],
            "action_id": body["action_id"], "script_id": context["script_id"],
            "error_code": incident.get("error_code"), "service": incident.get("service"),
            "environment": incident.get("environment"), "target": target,
            "requested_by": requested_by, "comment": comment,
        })
        if created:
            WorkflowStore().notify(
                "approval_requested", incident,
                f"[결재 요청] {incident.get('error_code')} · {context['script_id']}",
                f"{requested_by} 님이 {incident.get('service')} 조치 결재를 요청했습니다.",
            )
        return jsonify(status="pending" if created else "already_pending", approval=approval), 201 if created else 200
    except (ValueError, TypeError) as exc:
        return _blocked(str(exc))
    except Exception as exc:
        return jsonify(status="unavailable", error=type(exc).__name__), 503


@workflow_blueprint.get("/api/v1/approvals")
def list_approvals():
    status = request.args.get("status")
    incident_id = request.args.get("incident_id")
    limit = max(1, min(request.args.get("limit", default=50, type=int) or 50, 200))
    try:
        statuses = [item for item in (status or "").split(",") if item] or None
        approvals = WorkflowStore().list_approvals(statuses, incident_id, limit)
    except Exception as exc:
        return jsonify(status="unavailable", approvals=[], error=type(exc).__name__), 503
    return jsonify(status="ready", approvals=approvals)


def _current_body(approval, approver):
    """결재 시점의 최신 추천에서 같은 스크립트·대상의 조치를 찾는다."""
    incident = repository.get_operational_incident(approval["incident_id"])
    if not incident:
        raise ValueError("incident not found")
    recommendation_id = incident.get("latest_recommendation_id")
    recommendation = repository.get_recommendation(recommendation_id) if recommendation_id else None
    if not recommendation:
        raise ValueError("recommendation does not belong to incident")
    recommendation = bind_recommendation(incident, recommendation)
    action = next((item for item in recommendation.get("actions", [])
                   if item.get("script_id") == approval["script_id"]
                   and approval["target"] in (item.get("targets") or [])), None)
    if action is None:
        raise ValueError("action not allowed for incident")
    return {
        "incident_id": incident["incident_id"], "recommendation_id": recommendation_id,
        "action_id": action["action_id"], "incident_version": incident.get("version"),
        "approved_by": approver, "target": approval["target"],
    }


@workflow_blueprint.post("/api/v1/approvals/<approval_id>/approve")
def approve(approval_id):
    """관리자 결재 승인 → 실제 조치 실행."""
    from routes.remediation_routes import execute_action

    store = WorkflowStore()
    try:
        approver = _text(request.get_json(silent=True) or {}, "approver")
    except ValueError as exc:
        return _blocked(str(exc))
    approval = store.get_approval(approval_id)
    if approval is None:
        return jsonify(status="not_found"), 404
    if approval["status"] != "PENDING":
        return jsonify(status="already_decided", approval=approval), 409
    if not store.claim_approval(approval_id, approver):
        return jsonify(status="already_decided", approval=store.get_approval(approval_id)), 409
    try:
        body = _current_body(approval, approver)
        payload, status = execute_action(body)
    except (ValueError, TypeError) as exc:
        payload, status = {"status": "blocked", "reason": str(exc)}, 409
    except Exception as exc:
        payload, status = {"status": "unavailable", "error": type(exc).__name__}, 503
    if payload.get("execution_id"):
        approval = store.finish_approval(
            approval_id, "APPROVED", execution_id=payload["execution_id"],
            result_status=payload.get("status"), last_error=None)
    elif payload.get("reason") in ACTIONABLE_ERRORS:
        # 추천 만료·장애 상태 변경 등 다시 시도해도 실행할 수 없는 결재는 종료한다.
        approval = store.finish_approval(
            approval_id, "FAILED", result_status=payload.get("status"),
            last_error=payload.get("reason"))
    else:
        # 일시적 차단(Agent 연결, 이중화 조건 등)은 결재 대기로 되돌려 재시도할 수 있게 한다.
        approval = store.finish_approval(
            approval_id, "PENDING", decided_by=None, decided_at=None,
            last_error=payload.get("reason") or payload.get("status"))
    incident = repository.get_operational_incident(approval["incident_id"]) or {}
    store.notify(
        "approval_decided", incident,
        f"[결재 {'승인' if approval['status'] == 'APPROVED' else '처리 실패' if approval['status'] == 'FAILED' else '보류'}] {approval.get('error_code')} · {approval['script_id']}",
        f"{approver} — 결과: {payload.get('status')}" + (f" ({payload.get('reason')})" if payload.get("reason") else ""),
    )
    return jsonify({**redact(payload), "approval": approval}), status


@workflow_blueprint.post("/api/v1/approvals/<approval_id>/reject")
def reject(approval_id):
    store = WorkflowStore()
    try:
        body = request.get_json(silent=True) or {}
        approver = _text(body, "approver")
        reason = _text(body, "reason", limit=1000, required=False)
    except ValueError as exc:
        return _blocked(str(exc))
    approval, changed = store.reject_approval(approval_id, approver, reason)
    if approval is None:
        return jsonify(status="not_found"), 404
    if not changed:
        return jsonify(status="already_decided", approval=approval), 409
    incident = repository.get_operational_incident(approval["incident_id"]) or {}
    store.notify("approval_decided", incident,
                 f"[결재 반려] {approval.get('error_code')} · {approval['script_id']}",
                 f"{approver} — 사유: {reason or '미입력'}")
    return jsonify(status="rejected", approval=approval)


# ---------------------------------------------------------------- 보류(킵)
@workflow_blueprint.post("/api/v1/incidents/<incident_id>/hold")
def hold_incident(incident_id):
    try:
        body = request.get_json(silent=True) or {}
        operator = _text(body, "operator")
        reason = _text(body, "reason", limit=1000)
        incident = repository.get_operational_incident(incident_id)
        if not incident:
            return jsonify(status="not_found"), 404
        if incident_id in WorkflowStore().pending_incident_ids():
            return _blocked("approval pending; reject the approval before holding")
        held = operational_incident_service.hold(incident, operator, reason)
        WorkflowStore().notify("incident_held", held, f"[보류] {held.get('error_code')}",
                               f"{operator} — 사유: {reason}")
        return jsonify(status="held", incident=held)
    except ValueError as exc:
        return _blocked(str(exc))
    except RuntimeError:
        return _blocked("incident changed; reload details")
    except Exception as exc:
        return jsonify(status="unavailable", error=type(exc).__name__), 503


@workflow_blueprint.post("/api/v1/incidents/<incident_id>/release")
def release_incident(incident_id):
    try:
        operator = _text(request.get_json(silent=True) or {}, "operator")
        incident = repository.get_operational_incident(incident_id)
        if not incident:
            return jsonify(status="not_found"), 404
        released = operational_incident_service.release(incident, operator)
        return jsonify(status="released", incident=released)
    except ValueError as exc:
        return _blocked(str(exc))
    except RuntimeError:
        return _blocked("incident changed; reload details")
    except Exception as exc:
        return jsonify(status="unavailable", error=type(exc).__name__), 503


@workflow_blueprint.get("/api/v1/incidents/<incident_id>/history")
def incident_history(incident_id):
    incident = repository.get_operational_incident(incident_id)
    if not incident:
        return jsonify(status="not_found"), 404
    return jsonify(redact({"status": "ready", **similar_history(repository, incident)}))


# ------------------------------------------------------- 에러별 예외 처리 규칙
@workflow_blueprint.get("/api/v1/exception-rules")
def list_rules():
    return jsonify(status="ready", rules=WorkflowStore().list_rules())


@workflow_blueprint.post("/api/v1/exception-rules")
def create_rule():
    """규칙을 저장하고, 현재 열려 있는 같은 오류의 장애도 즉시 보류·알림한다."""
    try:
        store = WorkflowStore()
        rule, created = store.create_rule(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify(status="invalid_request", reason=str(exc)), 400
    held = []
    incident_id = (request.get_json(silent=True) or {}).get("incident_id")
    if isinstance(incident_id, str) and incident_id:
        incident = repository.get_operational_incident(incident_id)
        if (incident and store.match_rule(incident) and incident.get("status") not in {"ON_HOLD", "RESOLVED", "REMEDIATING"}
                and not incident.get("active_execution_id") and incident_id not in store.pending_incident_ids()):
            try:
                updated = operational_incident_service.hold(
                    incident, rule["created_by"], rule["reason"], source="exception_rule", rule=rule)
                store.notify("exception_hold", updated, f"[예외 처리] {updated.get('error_code')} 자동 보류",
                             f"{updated.get('service')} — 예외 처리 규칙 등록으로 보류했습니다. 사유: {rule['reason']}",
                             rule=rule)
                held.append(incident_id)
            except (ValueError, RuntimeError):
                pass
    return jsonify(status="created" if created else "exists", rule=rule, held_incidents=held), 201 if created else 200


@workflow_blueprint.delete("/api/v1/exception-rules/<rule_id>")
def delete_rule(rule_id):
    if not WorkflowStore().delete_rule(rule_id):
        return jsonify(status="not_found"), 404
    return jsonify(status="deleted")


# -------------------------------------------------------------------- 알림
@workflow_blueprint.get("/api/v1/notifications")
def notifications():
    limit = max(1, min(request.args.get("limit", default=30, type=int) or 30, 100))
    try:
        items, unread = WorkflowStore().list_notifications(limit)
    except Exception as exc:
        return jsonify(status="unavailable", notifications=[], unread=0, error=type(exc).__name__), 503
    return jsonify(status="ready", notifications=items, unread=unread)


@workflow_blueprint.post("/api/v1/notifications/read")
def read_notifications():
    return jsonify(status="ok", updated=WorkflowStore().mark_notifications_read())
