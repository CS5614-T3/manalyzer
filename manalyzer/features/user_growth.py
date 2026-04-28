from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from manalyzer.features.common import (
    create_analysis_result,
    fetch_all,
    insert_rows,
    parse_datetime,
    replace_current_result,
)

# from manalyzer.logger import get_logger

# logger = get_logger(__name__)


DAILY_DAYS = 7
WEEKLY_WEEKS = 5
MONTHLY_4WEEK_BUCKETS = 3


def day_start(value):
    # value: date-like object from created_at.date()
    # Return the UTC midnight timestamp used as the daily x-axis value.
    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)


def window_start(analysis_day, days_back):
    # analysis_day: latest available snapshot day
    # days_back: number of days to move backward from analysis_day
    return analysis_day - timedelta(days=days_back)


def latest_daily_users(snapshots):
    # snapshots: rows from instances_snapshot_raw
    # latest: maps (instance_id, day) to the newest snapshot timestamp and users value.
    latest = {}

    for row in snapshots:
        instance_id = row.get("id")
        created_at = parse_datetime(row.get("created_at"))
        if not instance_id or created_at is None:
            continue

        day = day_start(created_at.date())
        key = (instance_id, day)
        current = latest.get(key)

        # If there are multiple snapshots on the same day, keep only the newest one.
        if current is None or created_at > current[0]:
            latest[key] = (created_at, float(row.get("users") or 0))

    # daily_by_instance: {instance_id: {day: users}}
    daily_by_instance = defaultdict(dict)
    for (instance_id, day), (_created_at, users) in latest.items():
        daily_by_instance[instance_id][day] = users
    return daily_by_instance


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


def write_user_result(supabase, target_type, target_id, daily_values, analysis_day):
    # target_type/target_id identify either one instance or the global result.
    if not daily_values:
        return

    period_values = build_period_values(daily_values, analysis_day)
    result_id = create_analysis_result(
        supabase,
        "user_growth",
        time_from=min(min(values) for values in period_values.values() if values),
        time_to=analysis_day,
        target_type=target_type,
        target_id=target_id,
    )

    timeseries_rows = build_timeseries_rows(result_id, period_values)
    insert_rows(supabase, "res_timeseries", timeseries_rows)
    replace_current_result(supabase, "user_growth", result_id, target_type=target_type, target_id=target_id)


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
    for instance_id, daily_values in daily_by_instance.items():
        write_user_result(supabase, "instance", instance_id, daily_values, analysis_day)
        for day, value in daily_values.items():
            global_daily_values[day] += value

    write_user_result(supabase, "global", None, dict(global_daily_values), analysis_day)
