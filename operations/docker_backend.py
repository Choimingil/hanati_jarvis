"""Built-in Docker operations; never executes host commands or container shell scripts."""

import httpx


class DockerBackend:
    def __init__(self, manifest, client=None):
        if client is None:
            import docker

            client = docker.from_env(timeout=15)
        self.client = client
        self.manifest = manifest

    def container(self, action):
        container = self.client.containers.get(action["container"])
        container.reload()
        labels = container.attrs.get("Config", {}).get("Labels", {}) or {}
        if (
            labels.get("com.docker.compose.project") != self.manifest["compose_project"]
            or labels.get("com.docker.compose.service") != action["compose_service"]
        ):
            raise ValueError("container is not the registered Compose service")
        image = self.client.images.get(action["approved_image"])
        if container.attrs["Image"] != image.id:
            raise ValueError("container image differs from approved image")
        if (
            container.id == self.manifest.get("agent_container_id")
            or action["compose_service"] == "execution-agent"
        ):
            raise ValueError("agent cannot operate on itself")
        return container

    def snapshot(self, action):
        container = self.container(action)
        state = container.attrs["State"]
        return {
            "container_id": container.id,
            "image_id": container.attrs["Image"],
            "status": state["Status"],
            "running": state.get("Running", False),
            "paused": state.get("Paused", False),
        }

    def prechecks(self, action):
        container = self.container(action)
        checks = []
        peers = action.get("redundancy_peers", [])
        peer_results = []
        for name in peers:
            peer_action = {**action, "container": name}
            try:
                peer = self.container(peer_action)
                health = peer.attrs.get("State", {}).get("Health", {}).get("Status")
                peer_results.append(
                    peer.id != container.id
                    and peer.attrs["State"].get("Running") is True
                    and health == "healthy"
                )
            except Exception:
                peer_results.append(False)
        checks.append(
            {"name": "redundancy", "passed": bool(peers) and any(peer_results)}
        )
        labels = container.attrs.get("Config", {}).get("Labels", {}) or {}
        checks.append(
            {
                "name": "maintenance",
                "passed": labels.get("jarvis.maintenance", "false") == "false",
            }
        )
        # Restart does not replace the image/config/volumes. Require a stable,
        # running image and keep a snapshot to restore its previous runtime state.
        snapshot = self.snapshot(action)
        checks.append(
            {
                "name": "rollback_ready",
                "passed": snapshot["running"] and not snapshot["paused"],
                "snapshot": snapshot,
            }
        )
        return checks

    def perform(self, action):
        container = self.container(action)
        if action.get("operation") == "inspect":
            return {
                "status": "success",
                "container_id": container.id,
                "state": container.attrs["State"],
            }
        if action.get("operation") != "restart":
            raise ValueError("only inspect and restart operations are supported")
        container.restart(timeout=10)
        container.reload()
        return {
            "status": "success"
            if container.attrs["State"].get("Running")
            else "failed",
            "container_id": container.id,
            "state": container.attrs["State"],
        }

    def rollback(self, action, before):
        container = self.container(action)
        if (
            container.id != before["container_id"]
            or container.attrs["Image"] != before["image_id"]
        ):
            raise ValueError("container was replaced; automatic rollback blocked")
        if before["running"]:
            if container.attrs["State"].get("Paused"):
                container.unpause()
            container.start()
            if before["paused"]:
                container.pause()
        else:
            container.stop(timeout=10)
        container.reload()
        current = container.attrs["State"]
        ok = (
            current.get("Running") == before["running"]
            and current.get("Paused", False) == before["paused"]
        )
        return {
            "status": "success" if ok else "failed",
            "container_id": container.id,
            "state": current,
        }

    def verify(self, action):
        container = self.container(action)
        running = container.attrs["State"].get("Running") is True
        health = container.attrs["State"].get("Health", {}).get("Status")
        checks = [
            {"name": "container_running", "passed": running},
            {"name": "container_health", "passed": health == "healthy"},
        ]
        # Jarvis itself: prove that ingestion and a live worker can process a job.
        # This is a harmless INFO event, never an injected ERROR or real payment.
        if action.get("business_probe") != "jarvis_pipeline":
            raise ValueError("registered business probe is required")
        base = action.get("probe_url", "").rstrip("/")
        from urllib.parse import urlparse

        url = urlparse(base)
        if (
            url.scheme != "http"
            or url.hostname != action["compose_service"]
            or url.port != 8080
            or url.path not in {"", "/"}
        ):
            raise ValueError("probe URL must identify the registered Compose service")
        with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as http:
            response = http.post(
                base + "/api/v1/logs",
                json={
                    "level": "INFO",
                    "message": "Jarvis recovery pipeline probe",
                    "host": self.manifest["host"],
                    "service": action["compose_service"],
                    "environment": self.manifest["environment"],
                },
            )
            response.raise_for_status()
            ids = response.json().get("job_ids", [])
            passed = False
            import time

            for _ in range(10):
                if not ids:
                    break
                receipt = http.get(base + "/api/v1/analysis/jobs/" + ids[0])
                receipt.raise_for_status()
                status = receipt.json().get("status")
                if status == "completed":
                    passed = True
                    break
                if status == "failed":
                    break
                time.sleep(1)
        checks.append({"name": "ingest_and_analysis_pipeline", "passed": passed})
        return checks
