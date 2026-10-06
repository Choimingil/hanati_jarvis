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
