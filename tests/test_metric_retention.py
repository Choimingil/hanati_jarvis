import unittest
from unittest.mock import Mock

from elastic.metric_retention import delete_expired_metrics


class MetricRetentionTests(unittest.TestCase):

    def test_deletes_only_metrics_older_than_retention(self):
        client = Mock()
        client.delete_by_query.return_value = {
            "deleted": 12,
        }

        result = delete_expired_metrics(
            client,
            retention_days=14,
        )

        self.assertEqual(result["deleted"], 12)
        client.delete_by_query.assert_called_once_with(
            index="application-system-metrics",
            query={
                "range": {
                    "timestamp": {
                        "lt": "now-14d",
                    }
                }
            },
            conflicts="proceed",
            refresh=False,
            wait_for_completion=True,
            ignore_unavailable=True,
        )

    def test_rejects_non_positive_retention(self):
        with self.assertRaises(ValueError):
            delete_expired_metrics(
                Mock(),
                retention_days=0,
            )


if __name__ == "__main__":
    unittest.main()
