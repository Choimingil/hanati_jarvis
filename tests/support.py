"""In-memory repository used only by safety integration tests."""

import copy


class MemoryRepository:
    def __init__(self):
        self.incidents = {}
        self.recommendations = {}
        self.executions = {}
        self.verifications = []

    def get_operational_incident(self, identifier):
        return copy.deepcopy(self.incidents.get(identifier))

    def create_operational_incident(self, document):
        self.incidents[document["incident_id"]] = copy.deepcopy(document)

    def update_operational_incident(self, identifier, changes, expected_version):
        if self.incidents[identifier]["version"] != expected_version:
            raise RuntimeError("version conflict")
        self.incidents[identifier].update(copy.deepcopy(changes))
        return copy.deepcopy(self.incidents[identifier])

    def get_recommendation(self, identifier):
        return copy.deepcopy(self.recommendations.get(identifier))

    def get_remediation_execution(self, identifier):
        return copy.deepcopy(self.executions.get(identifier))

    def find_remediation_executions(self, recommendation_id):
        return [copy.deepcopy(record) for record in self.executions.values() if record.get("recommendation_id") == recommendation_id]

    def save_remediation_execution(self, document):
        if document["execution_id"] in self.executions:
            raise RuntimeError("duplicate")
        self.executions[document["execution_id"]] = copy.deepcopy(document)

    def save_recovery_verification(self, document):
        self.verifications.append(copy.deepcopy(document))
