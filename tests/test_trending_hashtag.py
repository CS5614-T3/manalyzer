from __future__ import annotations

from datetime import datetime, timezone
import unittest

from manalyzer.features.trending_hashtag import build_rank_rows, build_rank_stats


class TrendingHashtagAggregationTest(unittest.TestCase):
    def test_build_rank_stats_preaggregates_global_and_instance_values(self):
        analysis_day = datetime(2026, 4, 30, tzinfo=timezone.utc)
        joined_rows = [
            {
                "instance_id": "inst-a",
                "base_url": "a.example",
                "label": "python",
                "trend_id": "trend-1",
                "day": analysis_day,
                "uses": 10,
                "accounts": 3,
            },
            {
                "instance_id": "inst-b",
                "base_url": "b.example",
                "label": "python",
                "trend_id": "trend-2",
                "day": analysis_day,
                "uses": 5,
                "accounts": 2,
            },
        ]

        stats = build_rank_stats(joined_rows, analysis_day)

        self.assertEqual(stats[(None, "uses", 1)]["python"]["amount"], 15)
        self.assertEqual(stats[("inst-a", "uses", 1)]["python"]["amount"], 10)
        self.assertEqual(stats[("inst-b", "accounts", 1)]["python"]["amount"], 2)

        rank_rows = build_rank_rows(stats[(None, "uses", 1)], None, "uses", 1, 123)
        self.assertEqual(rank_rows[0]["amount"], 15)
        self.assertEqual(rank_rows[0]["extra_json"]["period_days"], 1)


if __name__ == "__main__":
    unittest.main()
