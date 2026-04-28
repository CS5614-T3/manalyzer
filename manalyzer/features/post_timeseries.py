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


def day_start(value):
    # value: date-like object from created_at.date()
    # Return UTC midnight for daily x-axis values.
    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)


def week_start(value):
    # value: date-like object
    # Use Monday as the start of each weekly bucket.
    monday = value - timedelta(days=value.weekday())
    return day_start(monday)


def month_start(value):
    # value: date-like object
    # Use the first day of the month as the monthly bucket key.
    return datetime(value.year, value.month, 1, tzinfo=timezone.utc)


def latest_daily_statuses(snapshots):
    # snapshots: rows from instances_snapshot_raw
    # latest: maps (instance_id, day) to the newest snapshot timestamp and statuses value.
    latest = {}

    for row in snapshots:
        instance_id = row.get("id")
        created_at = parse_datetime(row.get("created_at"))
        if not instance_id or created_at is None:
            continue

        day = day_start(created_at.date())
        key = (instance_id, day)
        current = latest.get(key)

        # If an instance has multiple snapshots on one day, keep the newest one.
        if current is None or created_at > current[0]:
            latest[key] = (created_at, float(row.get("statuses") or 0))

    # daily_by_instance: {instance_id: {day: statuses}}
    daily_by_instance = defaultdict(dict)
    for (instance_id, day), (_created_at, statuses) in latest.items():
        daily_by_instance[instance_id][day] = statuses
    return daily_by_instance


def aggregate_periods(daily_values):
    # daily_values: one instance or global daily statuses series
    # Weekly and monthly values are sums of the daily values in each bucket.
    weekly_values = defaultdict(float)
    monthly_values = defaultdict(float)

    for day, value in daily_values.items():
        weekly_values[week_start(day.date())] += value
        monthly_values[month_start(day.date())] += value

    return {
        "d": dict(daily_values),
        "w": dict(weekly_values),
        "m": dict(monthly_values),
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


def write_timeseries_result(supabase, target_type, target_id, daily_values):
    # target_type/target_id identify either one instance or the global result.
    if not daily_values:
        return

    days = sorted(daily_values)
    result_id = create_analysis_result(
        supabase,
        "post_timeseries",
        time_from=days[0],
        time_to=days[-1],
        target_type=target_type,
        target_id=target_id,
    )

    period_values = aggregate_periods(daily_values)
    timeseries_rows = build_timeseries_rows(result_id, period_values)
    insert_rows(supabase, "res_timeseries", timeseries_rows)
    replace_current_result(supabase, "post_timeseries", result_id, target_type=target_type, target_id=target_id)


def run(supabase):
    # logger.info("Running feature: post_timeseries")
    # Load status snapshots for all instances, ordered by snapshot time.
    snapshots = fetch_all(supabase, "instances_snapshot_raw", "id,created_at,statuses", order="created_at")

    daily_by_instance = latest_daily_statuses(snapshots)
    if not daily_by_instance:
        print("post_timeseries skipped: no instances_snapshot_raw rows")
        return

    # global_daily_values: sum of instance-level daily statuses by date.
    global_daily_values = defaultdict(float)
    for instance_id, daily_values in daily_by_instance.items():
        write_timeseries_result(supabase, "instance", instance_id, daily_values)
        for day, value in daily_values.items():
            global_daily_values[day] += value

    write_timeseries_result(supabase, "global", None, dict(global_daily_values))
