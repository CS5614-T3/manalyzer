from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from manalyzer.features.common import (
    create_analysis_results,
    day_start,
    fetch_all,
    insert_rows,
    latest_daily_metric,
    replace_current_results,
)

# from manalyzer.logger import get_logger

# logger = get_logger(__name__)


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
    # If an instance has multiple snapshots on one day, keep the newest one.
    return latest_daily_metric(snapshots, "statuses")


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


def build_timeseries_result(result_id, target_type, target_id, daily_values):
    days = sorted(daily_values)
    period_values = aggregate_periods(daily_values)
    return {
        "current": {
            "result_id": result_id,
            "target_type": target_type,
            "target_id": target_id,
        },
        "result_spec": {
            "time_from": days[0],
            "time_to": days[-1],
            "target_type": target_type,
            "target_id": target_id,
        },
        "timeseries_rows": build_timeseries_rows(result_id, period_values),
    }


def write_timeseries_results(supabase, result_inputs):
    result_inputs = [item for item in result_inputs if item["daily_values"]]
    result_specs = [
        {
            "time_from": min(item["daily_values"]),
            "time_to": max(item["daily_values"]),
            "target_type": item["target_type"],
            "target_id": item["target_id"],
        }
        for item in result_inputs
    ]
    result_ids = create_analysis_results(supabase, "post_timeseries", result_specs)

    timeseries_rows = []
    current_rows = []
    for result_id, item in zip(result_ids, result_inputs):
        built = build_timeseries_result(
            result_id,
            item["target_type"],
            item["target_id"],
            item["daily_values"],
        )
        timeseries_rows.extend(built["timeseries_rows"])
        current_rows.append(built["current"])

    insert_rows(supabase, "res_timeseries", timeseries_rows)
    replace_current_results(supabase, "post_timeseries", current_rows)


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
    write_timeseries_results(supabase, result_inputs)
