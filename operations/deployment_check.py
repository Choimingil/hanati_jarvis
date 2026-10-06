"""Read-only deployment checks inside the existing Compose image."""

import argparse
import json
import time
import httpx

EXPECTED = {
    "elasticsearch": 1536,
    "qdrant": 512,
    "redis": 384,
    "aiops": 1024,
    "analysis-worker": 1536,
    "llm-agent": 256,
    "collector": 192,
    "fluent-bit": 128,
}


def inspect_container(container, memory_mib):
    container.reload()
    attrs = container.attrs
    state = attrs.get("State", {})
    config = attrs.get("HostConfig", {})
    health = state.get("Health", {}).get("Status")
    return {
        "name": container.name,
        "running": state.get("Running") is True,
        "health": health,
        "oom_killed": state.get("OOMKilled", False),
        "restart_count": attrs.get("RestartCount", 0),
        "memory_limit_bytes": config.get("Memory"),
        "cpu_limit_nanocpus": config.get("NanoCpus"),
        "passed": state.get("Running") is True
        and not state.get("OOMKilled")
        and health in {None, "healthy"}
        and config.get("Memory") == memory_mib * 1024**2
        and config.get("MemorySwap") == config.get("Memory")
        and 0 < config.get("NanoCpus", 0) <= 2_000_000_000,
    }


def main():
    import docker

    parser = argparse.ArgumentParser()
    parser.add_argument("--wait-seconds", type=int, default=30)
    parser.add_argument("--include-agent", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.wait_seconds <= 60:
        parser.error("wait must be 0..60 seconds")
    client = docker.from_env(timeout=5)
    deadline = time.monotonic() + args.wait_seconds
    required = {**EXPECTED, **({"execution-agent": 192} if args.include_agent else {})}
    while True:
        checks = []
        for service, memory in required.items():
            try:
                containers = client.containers.list(
                    all=True,
                    filters={
                        "label": [
                            "com.docker.compose.project=hanati-jarvis",
                            "com.docker.compose.service=" + service,
                        ]
                    },
                )
                checks.append(
                    inspect_container(containers[0], memory)
                    if len(containers) == 1
                    else {
                        "name": service,
                        "passed": False,
                        "reason": "expected one container",
                    }
                )
            except Exception as exc:
                checks.append(
                    {"name": service, "passed": False, "reason": type(exc).__name__}
                )
        for service in ["elastic-init", "qdrant-init"]:
            try:
                containers = client.containers.list(
                    all=True,
                    filters={
                        "label": [
                            "com.docker.compose.project=hanati-jarvis",
                            "com.docker.compose.service=" + service,
                        ]
                    },
                )
                state = containers[0].attrs["State"] if len(containers) == 1 else {}
                checks.append(
                    {
                        "name": service,
                        "passed": state.get("Status") == "exited"
                        and state.get("ExitCode") == 0,
                    }
                )
            except Exception as exc:
                checks.append(
                    {"name": service, "passed": False, "reason": type(exc).__name__}
                )
        try:
            response = httpx.get("http://aiops:8080/health", timeout=3, trust_env=False)
            body = response.json()
            checks.append(
                {
                    "name": "api_and_worker_readiness",
                    "passed": response.status_code == 200 and body.get("ready") is True,
                    "collection_status": body.get("status"),
                }
            )
        except Exception as exc:
            checks.append(
                {
                    "name": "api_and_worker_readiness",
                    "passed": False,
                    "reason": type(exc).__name__,
                }
            )
        passed = all(c["passed"] for c in checks)
        if passed or time.monotonic() >= deadline:
            break
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    info = client.info()
    print(
        json.dumps(
            {
                "passed": passed,
                "server": {
                    "memory_bytes": info.get("MemTotal"),
                    "cpus": info.get("NCPU"),
                },
                "checks": checks,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    client.close()
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
