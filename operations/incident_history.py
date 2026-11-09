"""같은(유사한) 오류가 과거에 어떻게 조치되었는지 조회한다.

Incident ID는 fingerprint(환경·서비스·오류 코드·정규화 메시지)로 정해지므로 같은
오류가 재발하면 같은 Incident가 REOPENED 된다. 그래서 처리 완료(RESOLVED) 시점마다
`resolution_history`에 조치 방법을 누적하고, 같은 오류 코드를 가진 다른 서비스·환경의
Incident 이력도 함께 모아 보여준다.
"""

from config import SCRIPT_DESCRIPTIONS
from utils.time_utils import now_iso

MAX_RESOLUTION_HISTORY = 50


def _method_type(script_id, manual):
    if manual:
        return "manual"
    if str(script_id or "").startswith("LEARNED-"):
        return "learned_script"
    return "script" if script_id else "unknown"


def resolution_entry(incident, changes=None, manual_action=None):
    """RESOLVED 전환 시점의 조치 내용을 한 줄 이력으로 만든다."""
    merged = {**(incident or {}), **(changes or {})}
    execution = merged.get("last_execution") or {}
    script_id = None if manual_action else execution.get("script_id")
    if manual_action:
        method = manual_action.get("method")
        operator = manual_action.get("operator")
    else:
        method = SCRIPT_DESCRIPTIONS.get(script_id, script_id) if script_id else None
        operator = execution.get("operator")
    return {
        "resolved_at": merged.get("recovered_at") or now_iso(),
        "incident_id": merged.get("incident_id"),
        "service": merged.get("service"),
        "environment": merged.get("environment"),
        "error_code": merged.get("error_code"),
        "method_type": _method_type(script_id, manual_action),
        "script_id": script_id,
        "method": method or "기록된 조치 내용 없음",
        "operator": operator,
        "confirmation": merged.get("recovery_confirmation"),
        "execution_id": None if manual_action else execution.get("execution_id"),
        "attachment": (manual_action or {}).get("attachment", {}).get("filename") if manual_action else None,
    }


def with_resolution(incident, changes, manual_action=None):
    """changes에 resolution_history 누적분을 더해 돌려준다."""
    history = list((incident or {}).get("resolution_history") or [])
    history.append(resolution_entry(incident, changes, manual_action))
    return {**changes, "resolution_history": history[-MAX_RESOLUTION_HISTORY:]}


def _legacy_entry(incident):
    """resolution_history 도입 이전에 처리 완료된 Incident도 이력으로 보여준다."""
    if incident.get("status") != "RESOLVED":
        return []
    manual = next((item for item in reversed(incident.get("manual_actions") or [])
                   if item.get("registration_id") == incident.get("last_manual_action_id")), None)
    if incident.get("recovery_confirmation") not in {"operator_report", "pending_manual"}:
        manual = None
    return [resolution_entry(incident, manual_action=manual)]


def similar_history(repository, incident, limit=10):
    """현재 Incident와 같은 오류 코드(미등록 오류는 같은 정규화 메시지)의 과거 조치 이력."""
    error_code = incident.get("error_code")
    search = getattr(repository, "search_similar_incidents", None)
    candidates = []
    if callable(search):
        try:
            candidates = search(error_code, incident.get("normalized_message"), limit=50) or []
        except Exception:
            candidates = []
    if not any(item.get("incident_id") == incident.get("incident_id") for item in candidates):
        candidates.append(incident)
    entries = []
    for candidate in candidates:
        same_code = candidate.get("error_code") == error_code
        if error_code in {None, "UNKNOWN_ERROR"}:
            same_code = same_code and candidate.get("normalized_message") == incident.get("normalized_message")
        if not same_code:
            continue
        resolved = candidate.get("resolution_history") or _legacy_entry(candidate)
        for entry in resolved:
            entries.append({
                **entry,
                "kind": "resolution",
                "same_incident": candidate.get("incident_id") == incident.get("incident_id"),
            })
        for hold in candidate.get("hold_history") or []:
            entries.append({
                "kind": "hold", "resolved_at": hold.get("held_at"), "incident_id": candidate.get("incident_id"),
                "service": candidate.get("service"), "environment": candidate.get("environment"),
                "error_code": candidate.get("error_code"), "method_type": "hold",
                "method": hold.get("reason"), "operator": hold.get("operator"),
                "confirmation": hold.get("source"), "released_at": hold.get("released_at"),
                "same_incident": candidate.get("incident_id") == incident.get("incident_id"),
            })
    entries.sort(key=lambda item: str(item.get("resolved_at") or ""), reverse=True)
    resolutions = [item for item in entries if item["kind"] == "resolution"]
    summary = None
    if resolutions:
        counts = {}
        for item in resolutions:
            key = item.get("script_id") or item.get("method")
            counts[key] = counts.get(key, 0) + 1
        best = max(counts.items(), key=lambda pair: pair[1])
        latest = resolutions[0]
        summary = {
            "resolved_count": len(resolutions),
            "most_common_method": next(item["method"] for item in resolutions
                                       if (item.get("script_id") or item.get("method")) == best[0]),
            "most_common_count": best[1],
            "latest_method": latest["method"],
            "latest_resolved_at": latest.get("resolved_at"),
        }
    return {"summary": summary, "entries": entries[:limit]}
