import importlib
import json
import os
from pathlib import Path
import sys
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from aiops.operational_incident_service import OperationalIncidentService
from log_normalizer import normalize_log
from operations.worker import start_heartbeat
from tests.support import MemoryRepository


class GeneratorStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path("log_generator").resolve()))
        cls.generator = importlib.import_module("log_generator.main")

    def test_default_startup_prepares_file_without_generating_any_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shared" / "application.log"
            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(sys, "argv", ["main.py"]),
                patch.object(self.generator, "FLUENTBIT_LOG_PATH", path),
                patch.object(self.generator, "runner") as runner,
                patch.object(self.generator.threading, "Event") as event,
            ):
                self.generator.main()
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_text(), "")
            runner.run.assert_not_called()
            event.return_value.wait.assert_called_once()

    def test_random_generation_requires_explicit_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(sys, "argv", ["main.py", "--mode", "random"]),
                patch.object(self.generator, "FLUENTBIT_LOG_PATH", Path(directory) / "application.log"),
                patch.object(self.generator, "runner") as runner,
            ):
                self.generator.main()
            runner.run.assert_called_once()

    def test_real_default_process_stays_idle_without_writing_scenario_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(
                Path("log_generator"), root / "log_generator",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            environment = dict(os.environ)
            environment.pop("LOG_GENERATOR_MODE", None)
            environment["PYTHONPATH"] = str(root / "log_generator")
            process = subprocess.Popen(
                [sys.executable, str(root / "log_generator" / "main.py")],
                cwd=root, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    process.communicate(timeout=1.5)
                self.assertIsNone(process.poll())
            finally:
                process.terminate()
                output, errors = process.communicate(timeout=5)
            self.assertIn("Manual mode", output)
            self.assertEqual(errors, "")
            self.assertEqual((root / "fluentbit" / "application.log").read_text(), "")

    def test_manual_scenario_remains_functional_and_is_identified_as_simulation(self):
        from log_generator import trigger
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "application.log"
            with (
                patch.object(trigger, "FLUENTBIT_LOG_PATH", path),
                patch("scenario.scenario_runner.time.sleep"),
                patch("builtins.print"),
            ):
                result = trigger.run_scenario("dns_failure")
            logs = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual(result["error_code"], "DNS_RESOLUTION_FAILURE")
        self.assertTrue(any(log["level"] == "ERROR" for log in logs))
        self.assertTrue(all(log["synthetic"] for log in logs))
        self.assertTrue(all(log["environment"] == "simulation" for log in logs))

    def test_aggregated_details_preserve_origin_sources_and_latest_message(self):
        service = OperationalIncidentService(MemoryRepository())
        first = service.start(normalize_log({
            "level": "ERROR", "message": "timeout 123", "service": "order-api",
            "environment": "simulation", "host": "web01", "source": "dns", "synthetic": True,
        }), "DNS_RESOLUTION_FAILURE")
        second = service.start(normalize_log({
            "level": "ERROR", "message": "timeout 456", "service": "order-api",
            "environment": "simulation", "host": "web02", "source": "http", "synthetic": True,
        }), "DNS_RESOLUTION_FAILURE")
        self.assertEqual(first["incident_id"], second["incident_id"])
        self.assertEqual(second["latest_message"], "timeout 456")
        self.assertEqual(second["sources"], ["dns", "http"])
        self.assertEqual(second["affected_hosts"], ["web01", "web02"])
        self.assertTrue(second["synthetic"])
        self.assertEqual(second["source_type"], "scenario")

    def test_heartbeat_continues_during_blocked_analysis_and_recovers_from_redis_error(self):
        redis = Mock()
        refreshed = threading.Event()
        calls = []

        def record(*args, **kwargs):
            calls.append((args, kwargs))
            if len(calls) == 1:
                raise ConnectionError
            if len(calls) >= 3:
                refreshed.set()

        redis.set.side_effect = record
        with patch("builtins.print"):
            stopped, thread = start_heartbeat(redis, "test-worker", interval=0.02)
            try:
                # The analysis thread is waiting here; heartbeat still renews its lease.
                self.assertTrue(refreshed.wait(timeout=2))
                self.assertEqual(calls[-1][0][0], "jarvis:worker:test-worker")
                self.assertEqual(calls[-1][1]["ex"], 30)
            finally:
                stopped.set()
                thread.join(timeout=2)
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
