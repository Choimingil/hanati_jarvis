"""Regression checks for optional .env and explicit Compose variable forwarding.

These checks use `docker compose config` only; no Docker daemon is required.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


COMPOSE_FILE = Path(__file__).resolve().parents[1] / "docker-compose.yml"


class ComposeConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("docker"):
            raise unittest.SkipTest("Docker Compose CLI is not installed")
        result = subprocess.run(
            ["docker", "compose", "version"], capture_output=True, text=True
        )
        if result.returncode:
            raise unittest.SkipTest("Docker Compose CLI is not installed")

    def config(self, dotenv=None, shell=None):
        with tempfile.TemporaryDirectory(prefix="jarvis-compose-test-") as directory:
            root = Path(directory)
            shutil.copyfile(COMPOSE_FILE, root / "docker-compose.yml")
            if dotenv is not None:
                (root / ".env").write_text(dotenv, encoding="utf-8")
            environment = dict(os.environ)
            # Keep local user settings and secrets out of test configuration.
            for name in list(environment):
                if name.startswith(("COMPOSE_", "OPENAI_")) or name in {
                    "EXECUTION_AGENT_TOKEN", "COLLECTION_FRESHNESS_SECONDS",
                    "JOB_RETENTION_SECONDS", "LLM_EXTERNAL_ENABLED",
                }:
                    environment.pop(name)
            environment.update(shell or {})
            result = subprocess.run(
                ["docker", "compose", "--profile", "*", "config", "--format", "json"],
                cwd=root, env=environment, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)["services"]

    def test_missing_dotenv_uses_defaults(self):
        services = self.config()
        for name in ("aiops", "analysis-worker"):
            environment = services[name]["environment"]
            self.assertEqual(environment["OPENAI_API_KEY"], "")
            self.assertEqual(environment["COLLECTION_FRESHNESS_SECONDS"], "120")
            self.assertEqual(environment["JOB_RETENTION_SECONDS"], "604800")
            self.assertEqual(environment["REDIS_URL"], "redis://redis:6379/0")
        self.assertEqual(services["execution-agent"]["environment"]["EXECUTION_AGENT_TOKEN"], "")

    def test_dotenv_values_reach_all_intended_services(self):
        token = "test-token-" + "x" * 32
        services = self.config(
            "OPENAI_API_KEY=test-only-not-a-real-key\n"
            "COLLECTION_FRESHNESS_SECONDS=240\n"
            "JOB_RETENTION_SECONDS=3600\n"
            "LLM_EXTERNAL_ENABLED=false\n"
            "REDIS_URL=redis://127.0.0.1:6379/0\n"
            "EXECUTION_AGENT_TOKEN=" + token + "\n"
        )
        for name in ("aiops", "analysis-worker"):
            environment = services[name]["environment"]
            self.assertEqual(environment["OPENAI_API_KEY"], "test-only-not-a-real-key")
            self.assertEqual(environment["COLLECTION_FRESHNESS_SECONDS"], "240")
            self.assertEqual(environment["JOB_RETENTION_SECONDS"], "3600")
            self.assertEqual(environment["LLM_EXTERNAL_ENABLED"], "false")
            self.assertEqual(environment["REDIS_URL"], "redis://redis:6379/0")
        for name in ("aiops", "analysis-worker", "execution-agent"):
            self.assertEqual(services[name]["environment"]["EXECUTION_AGENT_TOKEN"], token)

    def test_shell_takes_precedence_over_dotenv(self):
        services = self.config(
            "OPENAI_MODEL=dotenv-test-model\n", {"OPENAI_MODEL": "shell-test-model"}
        )
        for name in ("aiops", "analysis-worker"):
            self.assertEqual(services[name]["environment"]["OPENAI_MODEL"], "shell-test-model")


if __name__ == "__main__":
    unittest.main()
