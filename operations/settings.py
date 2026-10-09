import json
import os
from pathlib import Path

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
REGISTRY_PATH = os.getenv("EXECUTION_TARGETS_FILE", "execution-targets.json")
FRESHNESS_SECONDS = int(os.getenv("COLLECTION_FRESHNESS_SECONDS", "120"))
JOB_RETENTION_SECONDS = int(os.getenv("JOB_RETENTION_SECONDS", "604800"))


def registry():
    path = Path(REGISTRY_PATH)
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError("execution targets must be an array")
    return data


def target_identity(entry):
    return {k: entry[k] for k in ("host", "environment", "service", "instance")}


def targets_for(incident):
    return [
        target_identity(t)
        for t in registry()
        if t.get("host") in incident.get("affected_hosts", [])
        and t.get("environment") == incident.get("environment")
        and t.get("service") == incident.get("service")
    ]


def bind_recommendation(incident, recommendation):
    """Bind each action to its current registered targets, including restored scripts."""
    if not isinstance(recommendation, dict):
        return recommendation
    from operations.scenario_scripts import targets_for_script
    from config import ERROR_RULES, SCRIPT_DESCRIPTIONS
    from runbooks import REMEDIATION_RUNBOOKS

    recommendation = dict(recommendation)
    registered = []
    if incident.get("synthetic") is True and incident.get("environment") == "simulation":
        for script_id in ERROR_RULES.get(incident.get("error_code"), {}).get("remediation_candidates", []):
            if targets_for_script(incident, script_id):
                registered.append(script_id)
        runbooks = list(recommendation.get("runbooks") or [])
        action_items = list(recommendation.get("actions") or [])
        for script_id in registered:
            if not any(item.get("script_id") == script_id for item in runbooks):
                runbooks.append({
                    **REMEDIATION_RUNBOOKS.get(script_id, {}), "script_id": script_id,
                    "action": SCRIPT_DESCRIPTIONS.get(script_id, script_id),
                    "estimated_cause": recommendation.get("cause") or recommendation.get("summary") or "기존 등록된 시나리오 대응 스크립트",
                    "confidence": 0, "registered_script": True,
                })
            if not any(item.get("script_id") == script_id for item in action_items):
                action_items.append({"action_id": "SCRIPT-" + script_id, "script_id": script_id})
        recommendation.update(runbooks=runbooks, actions=action_items)
    actions, targets = [], []
    for action in recommendation.get("actions", []):
        script_id = action.get("script_id")
        bound = targets_for_script(incident, script_id)
        if not (incident.get("synthetic") is True and incident.get("environment") == "simulation"):
            bound = [
                target_identity(entry) for entry in registry()
                if entry.get("host") in incident.get("affected_hosts", [])
                and entry.get("environment") == incident.get("environment")
                and entry.get("service") == incident.get("service")
                and ("scripts" not in entry or script_id in entry["scripts"])
            ]
        actions.append({**action, "targets": bound, **({"execution_mode": "simulation", "script_path": "test-runbooks/" + script_id + ".sh"} if script_id in registered else {})})
        for target in bound:
            if target not in targets:
                targets.append(target)
    return {**recommendation, "actions": actions, "targets": targets}


def with_execution_targets(incident):
    recommendation = incident.get("latest_recommendation")
    if not isinstance(recommendation, dict):
        return incident
    return {**incident, "latest_recommendation": bind_recommendation(incident, recommendation)}


def manual_action_available(incident):
    bound = with_execution_targets(incident)
    recommendation = bound.get("latest_recommendation") or {}
    return (
        not recommendation.get("targets")
        and bound.get("status") in {"ACTION_REQUIRED", "INVESTIGATING", "REOPENED", "MONITORING"}
        and not bound.get("active_execution_id")
        and (bound.get("status") != "MONITORING" or bound.get("recovery_confirmation") == "pending_manual")
    )
