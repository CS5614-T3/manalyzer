from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from manalyzer.features.common import (
    create_analysis_results,
    fetch_all,
    insert_rows,
    latest_daily_metric,
    replace_current_results,
)

# from manalyzer.logger import get_logger

# logger = get_logger(__name__)


DAILY_DAYS = 7
WEEKLY_WEEKS = 5
MONTHLY_4WEEK_BUCKETS = 3


def window_start(analysis_day, days_back):
    # analysis_day: latest available snapshot day
    # days_back: number of days to move backward from analysis_day
    return analysis_day - timedelta(days=days_back)


def latest_daily_users(snapshots):
    # snapshots: rows from instances_snapshot_raw
    # If there are multiple snapshots on the same day, keep only the newest one.
    return latest_daily_metric(snapshots, "users")


def sum_by_fixed_windows(daily_values, analysis_day, window_days, bucket_count):
    # daily_values: {day: users}
    # Build fixed-size buckets counted backward from the latest analysis day.
    buckets = {}
    for index in range(bucket_count - 1, -1, -1):
        bucket_end = analysis_day + timedelta(days=1) - timedelta(days=window_days * index)
        bucket_start = bucket_end - timedelta(days=window_days)

        # Bucket value is the sum of all daily user values inside [start, end).
        buckets[bucket_start] = sum(
            value for day, value in daily_values.items() if bucket_start <= day < bucket_end
        )
    return buckets


def build_period_values(daily_values, analysis_day):
    # daily_values: one instance or global daily user series
    # d = latest 7 days, w = latest five 7-day buckets, m = latest three 4-week buckets.
    daily_start = window_start(analysis_day, DAILY_DAYS - 1)
    daily_recent = {
        day: value for day, value in daily_values.items() if daily_start <= day <= analysis_day
    }

    return {
        "d": daily_recent,
        "w": sum_by_fixed_windows(daily_values, analysis_day, 7, WEEKLY_WEEKS),
        "m": sum_by_fixed_windows(daily_values, analysis_day, 28, MONTHLY_4WEEK_BUCKETS),
    }


def build_timeseries_rows(result_id, period_values):
    # period_values: {"d"|"w"|"m": {x_value: y_value}}
    # Convert grouped values into rows accepted by res_timeseries.
    rows = []
    for scale_type, values in period_values.items():
        for index, x_value in enumerate(sorted(values)):
            rows.append(
                {
                    "result_id": result_id,
                    "x_scale_type": scale_type,
                    "x_order": index,
                    "x_value": x_value.isoformat(),
                    "y_value": values[x_value],
                }
            )
    return rows


def build_user_result(result_id, target_type, target_id, period_values, analysis_day):
    return {
        "current": {
            "result_id": result_id,
            "target_type": target_type,
            "target_id": target_id,
        },
        "result_spec": {
            "time_from": min(min(values) for values in period_values.values() if values),
            "time_to": analysis_day,
            "target_type": target_type,
            "target_id": target_id,
        },
        "timeseries_rows": build_timeseries_rows(result_id, period_values),
    }


def write_user_results(supabase, result_inputs, analysis_day):
    result_inputs = [item for item in result_inputs if item["daily_values"]]
    prepared_results = []
    for item in result_inputs:
        period_values = build_period_values(item["daily_values"], analysis_day)
        prepared_results.append(
            {
                "target_type": item["target_type"],
                "target_id": item["target_id"],
                "period_values": period_values,
                "result_spec": {
                    "time_from": min(min(values) for values in period_values.values() if values),
                    "time_to": analysis_day,
                    "target_type": item["target_type"],
                    "target_id": item["target_id"],
                },
            }
        )

    result_specs = [
        item["result_spec"]
        for item in prepared_results
    ]
    result_ids = create_analysis_results(supabase, "user_growth", result_specs)

    timeseries_rows = []
    current_rows = []
    for result_id, item in zip(result_ids, prepared_results):
        built = build_user_result(
            result_id,
            item["target_type"],
            item["target_id"],
            item["period_values"],
            analysis_day,
        )
        timeseries_rows.extend(built["timeseries_rows"])
        current_rows.append(built["current"])

    insert_rows(supabase, "res_timeseries", timeseries_rows)
    replace_current_results(supabase, "user_growth", current_rows)


def run(supabase):
    # logger.info("Running feature: user_growth")
    # Load only users because active_users is no longer part of this feature.
    snapshots = fetch_all(
        supabase,
        "instances_snapshot_raw",
        "id,created_at,users",
        order="created_at",
    )

    daily_by_instance = latest_daily_users(snapshots)
    if not daily_by_instance:
        print("user_growth skipped: no instances_snapshot_raw rows")
        return

    # analysis_day is the latest date present in the snapshot dataset.
    analysis_day = max(day for daily_values in daily_by_instance.values() for day in daily_values)

    # global_daily_values: sum of instance-level daily user values by date.
    global_daily_values = defaultdict(float)
    result_inputs = []
    for instance_id, daily_values in daily_by_instance.items():
        result_inputs.append(
            {
                "target_type": "instance",
                "target_id": instance_id,
                "daily_values": daily_values,
            }
        )
        for day, value in daily_values.items():
            global_daily_values[day] += value

    result_inputs.append(
        {
            "target_type": "global",
            "target_id": None,
            "daily_values": dict(global_daily_values),
        }
    )
    write_user_results(supabase, result_inputs, analysis_day)
