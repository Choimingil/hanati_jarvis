from datetime import datetime, UTC
import json
import httpx
from concurrent.futures import ThreadPoolExecutor
from config import QDRANT_URL
from elastic.client import get_client
from operations.redis_store import client
import threading
import time

HTTP = httpx.Client(timeout=2, trust_env=False)
_CACHE = None
_CACHE_UNTIL = 0
_CACHE_LOCK = threading.Lock()

from operations.settings import FRESHNESS_SECONDS, registry


def probe(name, callback):
    try:
        return name, {"healthy": bool(callback())}
    except Exception as exc:
        return name, {"healthy": False, "error": type(exc).__name__}


def service_status():
    def qdrant():
        response = HTTP.get(QDRANT_URL.rstrip("/") + "/healthz", timeout=2)
        return response.status_code == 200

    callbacks = {
        "redis": lambda: client().ping(),
        "elasticsearch": lambda: (
            get_client().options(request_timeout=2, max_retries=0).ping()
        ),
        "qdrant": qdrant,
    }
    with ThreadPoolExecutor(max_workers=3) as pool:
        components = dict(pool.map(lambda item: probe(*item), callbacks.items()))
    collections = {}
    hosts = []
    queue = {}
    workers = 0
    if components["redis"]["healthy"]:
        redis = client()
        try:
            workers = sum(1 for _ in redis.scan_iter("jarvis:worker:*", count=100))
            collections = redis.hgetall("jarvis:collection")
            metric_hosts = redis.hgetall("jarvis:metric-hosts")
            configured = {t["host"] for t in registry()}
            for host in sorted(configured | set(metric_hosts)):
                details = json.loads(metric_hosts.get(host, "{}"))
                timestamp = details.get("timestamp")
                try:
                    age = (
                        datetime.now(UTC) - datetime.fromisoformat(timestamp)
                    ).total_seconds()
                except (TypeError, ValueError):
                    age = None
                hosts.append(
                    {
                        "host": host,
                        "last_sample_at": timestamp,
                        "age_seconds": round(age) if age is not None else None,
                        "connections_access_denied": details.get(
                            "connections_access_denied", False
                        ),
                        "status": "missing"
                        if age is None
                        else "stale"
                        if age > FRESHNESS_SECONDS
                        else "fresh",
                    }
                )
            queue = {
                "stream_length": redis.xlen("jarvis:analysis")
                + redis.xlen("jarvis:metrics-analysis"),
                "dead_letters": redis.xlen("jarvis:dead-letter"),
            }
            try:
                groups = redis.xinfo_groups("jarvis:analysis") + redis.xinfo_groups(
                    "jarvis:metrics-analysis"
                )
                queue["pending"] = sum(g["pending"] for g in groups)
            except Exception:
                queue["pending"] = 0
        except Exception as exc:
            components["redis"] = {"healthy": False, "error": type(exc).__name__}
    components["analysis_workers"] = {"healthy": workers > 0, "live_workers": workers}
    healthy = all(c["healthy"] for c in components.values())
    ready = healthy
    if any(h["status"] != "fresh" for h in hosts):
        healthy = False
    return {
        "status": "healthy" if healthy else "degraded",
        "ready": ready,
        "checked_at": datetime.now(UTC).isoformat(),
        "components": components,
        "collection": collections,
        "hosts": hosts,
        "queue": queue,
    }


def cached_service_status():
    global _CACHE, _CACHE_UNTIL
    with _CACHE_LOCK:
        if _CACHE is None or time.monotonic() >= _CACHE_UNTIL:
            _CACHE = service_status()
            _CACHE_UNTIL = time.monotonic() + 5
        return _CACHE
