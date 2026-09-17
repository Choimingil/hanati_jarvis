import unittest
from unittest.mock import patch

from elastic import mapping


class ElasticMappingTest(unittest.TestCase):
    def test_existing_index_receives_received_at_mapping(self):
        with patch.object(mapping, "es") as client:
            client.indices.exists.return_value = True

            mapping.create_log_index()

        client.indices.put_mapping.assert_called_once_with(
            index="application-logs",
            body={
                "properties": {
                    "received_at": {"type": "date"}
                }
            },
        )


if __name__ == "__main__":
    unittest.main()
