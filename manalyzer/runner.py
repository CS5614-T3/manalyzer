from __future__ import annotations

import argparse
import sys
import time

from manalyzer.db_client import get_db_client
# from manalyzer.logger import get_logger

from manalyzer.features.post_timeseries import run as run_post_timeseries
from manalyzer.features.user_growth import run as run_user_growth
from manalyzer.features.trending_hashtag import run as run_trending_hashtag
from manalyzer.features.trend_instances import run as run_trend_instances
from manalyzer.features.compare_servers import run as run_compare_servers
from manalyzer.features.map_feature import run as run_map_feature


FEATURES = {
    "post_timeseries": run_post_timeseries,
    "user_growth": run_user_growth,
    "trending_hashtag": run_trending_hashtag,
    "trend_instances": run_trend_instances,
    "compare_servers": run_compare_servers,
    "map": run_map_feature,
}


def run_feature(feature_name: str, supabase_client=None):

    if feature_name not in list(FEATURES.keys()):
        available = ", ".join(list(FEATURES.keys()))
        raise ValueError(f"Unknown feature: {feature_name}. Available: {available}")

    if supabase_client is None:
        supabase_client = get_db_client()
    runner = FEATURES[feature_name]
    
    started_at = time.perf_counter()
    try:
        runner(supabase_client)
        elapsed = time.perf_counter() - started_at
        print(f"{feature_name} done ({elapsed:.2f}s)")
    except Exception as e:
        elapsed = time.perf_counter() - started_at
        print(f"{feature_name} failed after {elapsed:.2f}s: {e}")


def run_all_features():
    supabase_client = get_db_client()
    for feature_name in list(FEATURES.keys()):
        run_feature(feature_name, supabase_client=supabase_client)
        


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mastodon Analyzer Runner")

    parser.add_argument(
        "--feature",
        type=str,
        help="Run a single feature by name",
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all features",
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available features",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.feature and not args.all and not args.list:
        # args.feature = "post_timeseries"
        args.all = True

    if args.list:
        print("Available features:")
        for name in list(FEATURES.keys()):
            print(f"- {name}")
        return

    if args.feature:
        run_feature(args.feature)
        return

    if args.all:
        run_all_features()
        
        return

    parser.print_help()
