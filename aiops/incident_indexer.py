from __future__ import annotations

from typing import Any

from qdrant_client.models import PointStruct

from config import QDRANT_COLLECTION
from qdrant.client import encode, get_client


class QdrantIncidentIndexer:
    def index(self, incident: dict[str, Any]) -> None:
        text = " ".join([
            incident.get("error_code", ""),
            incident.get("summary", ""),
            incident.get("root_cause", ""),
            " ".join(
                log.get("message", "")
                for log in incident.get("related_logs", [])
            ),
        ])
        get_client().upsert(
            collection_name=QDRANT_COLLECTION,
            points=[PointStruct(
                id=incident["incident_id"],
                vector=encode(text),
                payload=incident,
            )],
        )
