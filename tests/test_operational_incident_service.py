import unittest

from aiops.operational_incident_service import (
    OperationalIncidentService,
    build_fingerprint,
)


class FakeRepository:

    def __init__(self):
        self.incidents = {}

    def get_operational_incident(self, incident_id):
        value = self.incidents.get(incident_id)
        return dict(value) if value else None

    def create_operational_incident(self, document):
        if document["incident_id"] in self.incidents:
            raise RuntimeError("conflict")
        self.incidents[document["incident_id"]] = dict(document)

    def update_operational_incident(
        self, incident_id, changes, expected_version
    ):
        current = self.incidents[incident_id]
        if current["version"] != expected_version:
            raise RuntimeError("incident version conflict")
        current.update(changes)
        return dict(current)


class OperationalIncidentServiceTests(unittest.TestCase):

    def setUp(self):
        self.repository = FakeRepository()
        self.service = OperationalIncidentService(self.repository)
        self.log = {
            "environment": "prod",
            "service": "payment-api",
            "host": "payment-01",
            "message": "Connection timeout after 3001ms",
        }

    def test_dynamic_numbers_share_fingerprint(self):
        other = {
            **self.log,
            "message": "Connection timeout after 2987ms",
        }
        self.assertEqual(
            build_fingerprint(self.log, "DB_CONNECTION_FAILURE"),
            build_fingerprint(other, "DB_CONNECTION_FAILURE"),
        )

    def test_repeated_logs_update_same_incident(self):
        first = self.service.start(
            self.log, "DB_CONNECTION_FAILURE"
        )
        second = self.service.start(
            {**self.log, "host": "payment-02"},
            "DB_CONNECTION_FAILURE",
        )

        self.assertEqual(
            first["incident_id"], second["incident_id"]
        )
        self.assertEqual(second["occurrence_count"], 2)
        self.assertEqual(
            second["affected_hosts"],
            ["payment-01", "payment-02"],
        )

    def test_completion_binds_actions_and_version(self):
        incident = self.service.start(
            self.log, "DB_CONNECTION_FAILURE"
        )
        recommendation, updated = self.service.complete_analysis(
            incident,
            {
                "error_code": "DB_CONNECTION_FAILURE",
                "runbooks": [{
                    "script_id": "restart_db_connection_pool",
                }],
            },
        )

        self.assertEqual(updated["status"], "ACTION_REQUIRED")
        self.assertEqual(
            recommendation["incident_id"],
            incident["incident_id"],
        )
        self.assertEqual(
            recommendation["incident_version"],
            updated["version"],
        )
        self.assertEqual(
            recommendation["actions"][0]["script_id"],
            "restart_db_connection_pool",
        )


if __name__ == "__main__":
    unittest.main()
