from __future__ import annotations

from datetime import datetime, timezone
import unittest

from manalyzer.features.common import latest_daily_metric, parse_datetime
from manalyzer.features.post_timeseries import latest_daily_statuses
from manalyzer.features.user_growth import latest_daily_users


class TimeseriesSnapshotDedupTest(unittest.TestCase):
    def test_latest_daily_metric_keeps_newest_snapshot_per_instance_day(self):
        snapshots = [
            {"id": "inst-a", "created_at": "2026-04-01T09:00:00Z", "statuses": 10},
            {"id": "inst-a", "created_at": "2026-04-01T23:00:00Z", "statuses": 25},
            {"id": "inst-b", "created_at": "2026-04-01T12:00:00Z", "statuses": 7},
        ]

        daily_by_instance = latest_daily_metric(snapshots, "statuses")
        day = datetime(2026, 4, 1, tzinfo=timezone.utc)

        self.assertEqual(daily_by_instance["inst-a"][day], 25)
        self.assertEqual(daily_by_instance["inst-b"][day], 7)
        self.assertEqual(
            sum(values[day] for values in daily_by_instance.values()),
            32,
        )

    def test_timeseries_helpers_share_dedup_rule(self):
        snapshots = [
            {"id": "inst-a", "created_at": "2026-04-01T10:00:00Z", "statuses": 1, "users": 100},
            {"id": "inst-a", "created_at": "2026-04-01T18:00:00Z", "statuses": 2, "users": 120},
        ]
        day = datetime(2026, 4, 1, tzinfo=timezone.utc)

        self.assertEqual(latest_daily_statuses(snapshots)["inst-a"][day], 2)
        self.assertEqual(latest_daily_users(snapshots)["inst-a"][day], 120)

    def test_parse_datetime_normalizes_offsets_to_utc(self):
        parsed = parse_datetime("2026-04-02T01:00:00+09:00")

        self.assertEqual(parsed, datetime(2026, 4, 1, 16, 0, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
