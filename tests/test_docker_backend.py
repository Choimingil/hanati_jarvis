import copy
import types
import unittest
from operations.docker_backend import DockerBackend
from operations.privacy import redact


class DockerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.container = types.SimpleNamespace(
            id="container-one",
            reload=lambda: None,
            attrs={
                "Config": {
                    "Labels": {
                        "com.docker.compose.project": "jarvis",
                        "com.docker.compose.service": "aiops",
                    }
                },
                "Image": "sha256:approved",
                "State": {
                    "Status": "running",
                    "Running": True,
                    "Paused": False,
                    "Health": {"Status": "healthy"},
                },
            },
        )
        self.peer = copy.deepcopy(self.container)
        self.peer.id = "container-two"
        containers = {"one": self.container, "two": self.peer}
        client = types.SimpleNamespace(
            containers=types.SimpleNamespace(get=lambda name: containers[name]),
            images=types.SimpleNamespace(
                get=lambda name: types.SimpleNamespace(id="sha256:approved")
            ),
        )
        self.backend = DockerBackend({"compose_project": "jarvis"}, client=client)
        self.action = {
            "container": "one",
            "compose_service": "aiops",
            "approved_image": "hanati-aiops:local",
            "redundancy_peers": ["two"],
        }

    def test_foreign_project_or_unapproved_image_blocked(self):
        self.container.attrs["Config"]["Labels"]["com.docker.compose.project"] = "other"
        with self.assertRaises(ValueError):
            self.backend.container(self.action)
        self.container.attrs["Config"]["Labels"]["com.docker.compose.project"] = (
            "jarvis"
        )
        self.container.attrs["Image"] = "sha256:foreign"
        with self.assertRaises(ValueError):
            self.backend.container(self.action)

    def test_redundancy_requires_another_healthy_registered_container(self):
        self.assertTrue(all(c["passed"] for c in self.backend.prechecks(self.action)))
        self.peer.attrs["State"]["Health"]["Status"] = "unhealthy"
        self.assertFalse(self.backend.prechecks(self.action)[0]["passed"])
        self.action["redundancy_peers"] = ["one"]
        self.assertFalse(self.backend.prechecks(self.action)[0]["passed"])

    def test_maintenance_and_replacement_block_actions(self):
        self.container.attrs["Config"]["Labels"]["jarvis.maintenance"] = "true"
        self.assertFalse(self.backend.prechecks(self.action)[1]["passed"])
        before = {**self.backend.snapshot(self.action), "container_id": "replaced"}
        with self.assertRaises(ValueError):
            self.backend.rollback(self.action, before)

    def test_redaction_preserves_structural_ids_with_numeric_runs(self):
        identifier = "a1234567890123456789b1234567890123"
        self.assertEqual(
            redact({"job_ids": [identifier], "policy_digest": identifier}),
            {"job_ids": [identifier], "policy_digest": identifier},
        )
        self.assertNotEqual(
            redact({"message": "4111111111111111"})["message"], "4111111111111111"
        )
