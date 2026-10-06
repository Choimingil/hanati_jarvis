"""운영 중인 장애(Incident)의 식별, 집계, 상태 전환을 관리한다."""

import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from config import RECOMMENDATION_TTL_MINUTES
from utils.time_utils import now_iso
from operations.settings import targets_for
from operations.business import business_priority
import os


OPEN_STATUSES = {
    "DETECTED",
    "ANALYZING",
    "ACTION_REQUIRED",
    "INVESTIGATING",
    "REMEDIATING",
    "MONITORING",
    "REOPENED",
}


def normalize_message(message: str) -> str:
    value = message.lower()
    value = re.sub(
        r"[0-9a-f]{8}-[0-9a-f-]{27,}",
        "{uuid}",
        value,
    )
    value = re.sub(r"\d+(?:\.\d+)?", "{number}", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:240]


def build_fingerprint(
    log: dict[str, Any],
    error_code: str | None,
) -> str:
    return "|".join(
        [
            str(log.get("environment") or "unknown"),
            str(log.get("service") or "unknown"),
            error_code or "UNKNOWN_ERROR",
            normalize_message(str(log.get("message") or "")),
        ]
    )


def build_incident_id(fingerprint: str) -> str:
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16].upper()
    return f"INC-{digest}"


class OperationalIncidentService:
    def __init__(self, repository) -> None:
        self.repository = repository

    def start(
        self,
        log: dict[str, Any],
        error_code: str | None,
        ingestion_id: str | None = None,
    ) -> dict[str, Any]:
        fingerprint = build_fingerprint(log, error_code)
        incident_id = build_incident_id(fingerprint)
        existing = self.repository.get_operational_incident(incident_id)
        timestamp = now_iso()
        host = str(log.get("host") or "unknown")

        if existing is None:
            incident = {
                "incident_id": incident_id,
                "fingerprint": fingerprint,
                "environment": str(log.get("environment") or "unknown"),
                "service": str(log.get("service") or "unknown"),
                "error_code": error_code or "UNKNOWN_ERROR",
                "normalized_message": normalize_message(str(log.get("message") or "")),
                "representative_message": str(log.get("message") or ""),
                "status": "ANALYZING",
                "severity": "MEDIUM",
                **business_priority(log),
                "first_seen": timestamp,
                "last_seen": timestamp,
                "occurrence_count": 1,
                "affected_hosts": [host],
                "latest_recommendation_id": None,
                "latest_recommendation": None,
                "version": 1,
                "ingestion_ids": [ingestion_id] if ingestion_id else [],
            }
            try:
                self.repository.create_operational_incident(incident)
                return incident
            except Exception:
                # 같은 fingerprint가 동시에 최초 유입되면 한 요청만 create에
                # 성공한다. 나머지는 생성된 Incident를 다시 읽어 집계한다.
                existing = self.repository.get_operational_incident(incident_id)
                if existing is None:
                    raise

        if ingestion_id and ingestion_id in existing.get("ingestion_ids", []):
            return existing
        hosts = set(existing.get("affected_hosts") or [])
        hosts.add(host)
        count = int(existing.get("occurrence_count", 0)) + 1
        status = existing.get("status", "ANALYZING")
        if status == "RESOLVED":
            status = "REOPENED"
        priority = business_priority(log, count, existing)
        recommendation = existing.get("latest_recommendation") or {}
        try:
            expires = datetime.fromisoformat(
                recommendation.get("expires_at", "").replace("Z", "+00:00")
            )
            last = datetime.fromisoformat(
                existing.get("last_analysis_at", "").replace("Z", "+00:00")
            )
            cached = expires > datetime.now(UTC) and (
                datetime.now(UTC) - last
            ).total_seconds() < int(os.getenv("INCIDENT_REANALYSIS_SECONDS", "300"))
        except (ValueError, TypeError):
            cached = False
        observing = status in {"REMEDIATING", "MONITORING"}
        suppress = observing or (
            cached
            and status in {"ACTION_REQUIRED", "INVESTIGATING"}
            and sorted(hosts) == sorted(existing.get("affected_hosts", []))
            and priority["priority_rank"] >= existing.get("priority_rank", 4)
        )
        severity = "CRITICAL" if count >= 20 else "HIGH" if count >= 5 else "MEDIUM"
        updater = getattr(
            self.repository,
            "record_incident_occurrence",
            self.repository.update_operational_incident,
        )
        updated = updater(
            incident_id,
            {
                "status": status,
                "severity": severity,
                **priority,
                "last_seen": timestamp,
                "occurrence_count": count,
                "affected_hosts": sorted(hosts),
                "ingestion_ids": (
                    existing.get("ingestion_ids", [])
                    + ([ingestion_id] if ingestion_id else [])
                )[-1000:],
                "version": int(existing.get("version", 1)) + (0 if suppress else 1),
            },
            expected_version=int(existing.get("version", 1)),
            **(
                {"expected_count": existing.get("occurrence_count", 0)}
                if hasattr(self.repository, "record_incident_occurrence")
                else {}
            ),
        )
        updated["analysis_suppressed"] = suppress
        return updated

    def complete_analysis(
        self,
        incident: dict[str, Any],
        recommendation: dict[str, Any],
        status: str = "ACTION_REQUIRED",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        recommendation_id = "REC-" + uuid.uuid4().hex.upper()
        current_version = int(incident.get("version", 1))
        next_version = current_version + 1
        created_at = datetime.now(UTC)
        actions = []
        candidates = (
            recommendation.get("runbooks")
            or recommendation.get("recommended_actions")
            or []
        )
        for index, candidate in enumerate(candidates, start=1):
            script_id = candidate.get("script_id")
            if not script_id:
                continue
            actions.append(
                {
                    "action_id": f"ACTION-{index}",
                    "script_id": script_id,
                }
            )

        enriched = {
            **recommendation,
            "recommendation_id": recommendation_id,
            "incident_id": incident["incident_id"],
            "incident_version": next_version,
            "created_at": created_at.isoformat(),
            "expires_at": (
                created_at + timedelta(minutes=RECOMMENDATION_TTL_MINUTES)
            ).isoformat(),
            "actions": actions,
            "targets": targets_for(incident),
            "priority": incident.get("priority", "P3"),
            "business_impact": incident.get("business_impact", {}),
        }
        updated = self.repository.update_operational_incident(
            incident["incident_id"],
            {
                "status": status,
                "latest_recommendation_id": recommendation_id,
                "latest_recommendation": enriched,
                "last_analysis_at": created_at.isoformat(),
                "version": next_version,
            },
            expected_version=current_version,
        )
        return enriched, updated

    def transition(
        self,
        incident: dict[str, Any],
        status: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current_version = int(incident.get("version", 1))
        changes = {
            "status": status,
            "version": current_version + 1,
            "updated_at": now_iso(),
            **(extra or {}),
        }
        return self.repository.update_operational_incident(
            incident["incident_id"],
            changes,
            expected_version=current_version,
        )
