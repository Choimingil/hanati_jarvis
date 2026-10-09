"""Register an operator's externally performed action without executing input."""

import hashlib
import json
import re

from operations.privacy import redact
from operations.settings import manual_action_available
from utils.time_utils import now_iso


class ManualRemediationService:
    def __init__(self, repository):
        self.repository = repository

    def submit(self, body):
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        for field, limit in (("incident_id", 200), ("registration_id", 100), ("operator", 200), ("method", 8000)):
            value = body.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise ValueError("invalid " + field)
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", body["registration_id"]):
            raise ValueError("invalid registration_id")
        version = body.get("incident_version")
        if type(version) is not int or version < 1:
            raise ValueError("incident_version must be an integer")
        if body.get("performed") is not True:
            raise ValueError("manual action must already be performed")
        if type(body.get("recovered")) is not bool:
            raise ValueError("recovered must be a boolean")
        incident = self.repository.get_operational_incident(body["incident_id"])
        if incident is None:
            raise LookupError("incident not found")
        content = redact({
            "operator": body["operator"].strip(), "method": body["method"].strip(),
            "performed": True, "recovered": body["recovered"],
        })
        fingerprint = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
        history = list(incident.get("manual_actions") or [])
        existing = next((item for item in history if item["registration_id"] == body["registration_id"]), None)
        if existing:
            if existing["fingerprint"] != fingerprint:
                raise ValueError("registration id reused with different action")
            return {"status": "registered", "duplicate": True, "manual_action": existing, "incident": incident}
        if incident.get("version") != version:
            raise ValueError("incident changed; reload details before registering")
        if not manual_action_available(incident):
            raise ValueError("manual registration unavailable for this incident")
        if len(history) >= 100:
            raise ValueError("manual registration limit reached")
        timestamp = now_iso()
        action = {
            "registration_id": body["registration_id"], "fingerprint": fingerprint,
            "registered_at": timestamp, "incident_id": incident["incident_id"],
            "service": incident.get("service"), "environment": incident.get("environment"),
            "affected_hosts": incident.get("affected_hosts", []), "error_code": incident.get("error_code"),
            **content, "recovery_confirmation": "operator_report" if content["recovered"] else "pending",
        }
        changes = {
            "manual_actions": history + [action], "last_manual_action_id": action["registration_id"],
            "status": "RESOLVED" if content["recovered"] else "MONITORING",
            "recovery_confirmation": "operator_report" if content["recovered"] else "pending_manual",
            "version": version + 1, "updated_at": timestamp,
            **({"recovered_at": timestamp} if content["recovered"] else {}),
        }
        updated = self.repository.update_operational_incident(
            incident["incident_id"], changes, expected_version=version,
        )
        return {"status": "registered", "duplicate": False, "manual_action": action, "incident": updated}
