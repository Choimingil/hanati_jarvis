"""Present execution completion separately from confirmed incident recovery."""

from datetime import UTC, datetime


def execution_summary(record):
    if not isinstance(record, dict):
        return None
    result = record.get("result") or {}
    finished_at = result.get("finished_at")
    if isinstance(finished_at, (int, float)):
        finished_at = datetime.fromtimestamp(finished_at, UTC).isoformat()
    return {
        "execution_id": record.get("execution_id"),
        "script_id": record.get("script_id"),
        "operator": record.get("approved_by"),
        "finished_at": finished_at or record.get("approved_at"),
        "status": result.get("status"),
        "target": record.get("target"),
    }


def processing_summary(incident, execution=None):
    status = incident.get("status")
    confirmation = incident.get("recovery_confirmation")
    manual = next((
        item for item in reversed(incident.get("manual_actions") or [])
        if item.get("registration_id") == incident.get("last_manual_action_id")
    ), None) if confirmation in {"operator_report", "pending_manual"} else None
    execution = execution or incident.get("last_execution") or {}
    if status == "RESOLVED":
        return {
            "state": "completed", "label": "처리 완료",
            "completed_at": incident.get("recovered_at") or (manual or {}).get("registered_at") or execution.get("finished_at"),
            "operator": (manual or {}).get("operator") or execution.get("operator"),
            "method": (manual or {}).get("method") or execution.get("script_id"),
            "confirmation": confirmation or "recorded_resolution",
            "message": {
                "simulation": "등록 스크립트 실행 결과 확인이 완료되었습니다.",
                "operator_report": "운영자가 서비스 복구를 확인하고 처리를 완료했습니다.",
            }.get(confirmation, "복구 확인이 완료된 장애입니다."),
        }
    if status == "MONITORING":
        return {
            "state": "action_completed", "label": "조치 완료 · 복구 확인 대기",
            "completed_at": (manual or {}).get("registered_at") or execution.get("finished_at"),
            "operator": (manual or {}).get("operator") or execution.get("operator"),
            "method": (manual or {}).get("method") or execution.get("script_id"),
            "confirmation": confirmation,
            "message": "조치가 완료되었습니다. 서비스 복구 확인 후 처리가 완료됩니다.",
        }
    return {"state": "open", "label": "처리 진행중", "completed_at": None, "operator": None, "method": None, "confirmation": None, "message": ""}
