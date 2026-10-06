from __future__ import annotations

from typing import Any

from config import ERROR_RULES, INCIDENT_COOLDOWN_MINUTES
from utils.time_utils import now_iso


class MetricAnalysisService:
    def __init__(
        self,
        repository,
        case_searcher,
        recommendation_generator,
        feature_extractor,
        anomaly_detector,
        correlator,
        case_builder,
        incident_indexer,
        context_builder,
        incident_service=None,
    ) -> None:
        self.repository = repository
        self.case_searcher = case_searcher
        self.recommendation_generator = recommendation_generator
        self.feature_extractor = feature_extractor
        self.anomaly_detector = anomaly_detector
        self.correlator = correlator
        self.case_builder = case_builder
        self.incident_indexer = incident_indexer
        self.context_builder = context_builder
        self.incident_service = incident_service

    def analyze(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        host = snapshot.get("host", {}).get("hostname", "unknown")
        snapshots = self.repository.recent_metrics(host, minutes=15)
        if not any(
            item.get("timestamp") == snapshot.get("timestamp") for item in snapshots
        ):
            snapshots.append(snapshot)
        features = self.feature_extractor.extract(snapshots)
        events = self.anomaly_detector.detect(features)
        results = []

        for event in events:
            if self.repository.has_recent_incident(
                host,
                event["detection_code"],
                INCIDENT_COOLDOWN_MINUTES,
            ):
                results.append(
                    {
                        "status": "cooldown",
                        "detection_code": event["detection_code"],
                    }
                )
                continue

            logs = self.repository.recent_error_logs(host, minutes=10)
            correlation = self.correlator.correlate(event, logs)
            context = self.context_builder.build(event, features, correlation)
            operational = None
            if self.incident_service is not None:
                operational = self.incident_service.start(
                    {
                        "host": host,
                        "environment": snapshot.get("environment", "unknown"),
                        "service": snapshot.get("service", "unknown"),
                        "message": context["message"],
                    },
                    event["error_code"],
                    ingestion_id=(
                        snapshot.get("ingestion_id", "") + ":" + event["detection_code"]
                    )
                    if snapshot.get("ingestion_id")
                    else None,
                )
                if operational.get("status") in {"REMEDIATING", "MONITORING"}:
                    results.append(
                        {
                            "status": "observation_in_progress",
                            "incident_id": operational["incident_id"],
                        }
                    )
                    continue
            if operational and operational.get("analysis_suppressed"):
                persisted = getattr(
                    self.repository, "get_recommendation", lambda _: True
                )(operational.get("latest_recommendation_id"))
                if persisted:
                    results.append(
                        {
                            "status": "aggregated",
                            "incident_id": operational["incident_id"],
                        }
                    )
                    continue
            try:
                past_cases = self.case_searcher.search(
                    error_code=event["error_code"],
                    message=context["message"],
                    limit=3,
                )
            except Exception:
                past_cases = []

            rule = ERROR_RULES[event["error_code"]]
            recommendation = self.recommendation_generator.generate(
                error_code=event["error_code"],
                message=context["message"],
                diagnosis_results=context["diagnosis_results"],
                past_cases=past_cases,
                remediation_candidates=rule["remediation_candidates"],
            )
            if operational is not None:
                recommendation, operational = self.incident_service.complete_analysis(
                    operational, recommendation
                )
            incident = self.case_builder.build(
                host,
                event,
                features,
                correlation,
                recommendation,
            )
            self.repository.save_incident(incident)
            self.repository.save_recommendation(
                {
                    "timestamp": now_iso(),
                    "source": "metric_anomaly",
                    "incident_id": operational["incident_id"]
                    if operational
                    else incident["incident_id"],
                    "recommendation": recommendation,
                }
            )
            try:
                self.incident_indexer.index(incident)
                indexed = True
            except Exception:
                indexed = False
            results.append(
                {
                    "status": "recommended",
                    "incident_id": operational["incident_id"]
                    if operational
                    else incident["incident_id"],
                    "error_code": event["error_code"],
                    "detection_code": event["detection_code"],
                    "qdrant_indexed": indexed,
                    "recommendation": recommendation,
                }
            )

        return results
