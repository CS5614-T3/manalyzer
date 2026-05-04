from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timezone


PAGE_SIZE = 1000

# Stable task codes used by analysis_result and current_analysis_result.
TASK_TYPES = {
    "post_timeseries": {
        "task_type": 1,
        "task_name": "post_timeseries",
        "task_desc": "Global post/status volume over time",
    },
    "user_growth": {
        "task_type": 2,
        "task_name": "user_growth",
        "task_desc": "Global user count growth over time",
    },
    "trending_hashtag_uses_1d": {
        "task_type": 21,
        "task_name": "trending_hashtag_uses_1d",
        "task_desc": "Top hashtags by uses in the latest 1 day",
    },
    "trending_hashtag_uses_7d": {
        "task_type": 22,
        "task_name": "trending_hashtag_uses_7d",
        "task_desc": "Top hashtags by uses in the latest 7 days",
    },
    "trending_hashtag_uses_30d": {
        "task_type": 23,
        "task_name": "trending_hashtag_uses_30d",
        "task_desc": "Top hashtags by uses in the latest 30 days",
    },
    "trending_hashtag_accounts_1d": {
        "task_type": 24,
        "task_name": "trending_hashtag_accounts_1d",
        "task_desc": "Top hashtags by accounts in the latest 1 day",
    },
    "trending_hashtag_accounts_7d": {
        "task_type": 25,
        "task_name": "trending_hashtag_accounts_7d",
        "task_desc": "Top hashtags by accounts in the latest 7 days",
    },
    "trending_hashtag_accounts_30d": {
        "task_type": 26,
        "task_name": "trending_hashtag_accounts_30d",
        "task_desc": "Top hashtags by accounts in the latest 30 days",
    },
    "trend_instances": {
        "task_type": 4,
        "task_name": "trend_instances",
        "task_desc": "Top instances by public instance metrics",
    },
    "compare_servers": {
        "task_type": 5,
        "task_name": "compare_servers",
        "task_desc": "Comparable per-instance metrics",
    },
    "map": {
        "task_type": 6,
        "task_name": "map",
        "task_desc": "Instance distribution by language, category, and topic",
    },
}


def utc_now():
    # Return the current UTC timestamp for fallback result periods.
    return datetime.now(timezone.utc)


def iso(value):
    # value: datetime, date, string, or None
    # Convert Python date/time values into Supabase-friendly ISO strings.
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc).isoformat()
    return value


def parse_datetime(value):
    # value: datetime, date, ISO string, or unknown input
    # Normalize supported values to timezone-aware UTC datetimes.
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def day_start(value):
    # value: date-like object
    # Return UTC midnight for daily x-axis values.
    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)


def latest_daily_metric(snapshots, metric_name):
    # Keep only the newest snapshot per instance per UTC day before aggregating.
    latest = {}

    for row in snapshots:
        instance_id = row.get("id")
        created_at = parse_datetime(row.get("created_at"))
        if not instance_id or created_at is None:
            continue

        day = day_start(created_at.date())
        key = (instance_id, day)
        current = latest.get(key)
        if current is None or created_at > current[0]:
            latest[key] = (created_at, num(row.get(metric_name)))

    daily_by_instance = defaultdict(dict)
    for (instance_id, day), (_created_at, value) in latest.items():
        daily_by_instance[instance_id][day] = value
    return daily_by_instance


def parse_date(value):
    # value: datetime/date/ISO string
    # Return only the calendar date part when parsing succeeds.
    parsed = parse_datetime(value)
    if parsed is not None:
        return parsed.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def num(value, default=0.0):
    # Safely coerce numeric database values into float.
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_ratio(numerator, denominator):
    # Return None for empty or zero denominators to satisfy nullable numeric columns.
    denominator_value = num(denominator)
    if denominator_value <= 0:
        return None
    return num(numerator) / denominator_value


def normalize_array(value):
    # Supabase may return PostgreSQL arrays as lists, but tolerate strings too.
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Iterable):
        return [str(item) for item in value if item is not None and str(item)]
    return []


def fetch_all(supabase, table, select="*", order=None):
    # Supabase range queries are page-based, so fetch large tables in chunks.
    # rows: list of dictionaries returned by Supabase.
    rows = []
    start = 0

    while True:
        query = supabase.table(table).select(select)
        if order:
            query = query.order(order)
        response = query.range(start, start + PAGE_SIZE - 1).execute()
        page = response.data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        start += PAGE_SIZE


def task_meta(feature_name):
    # feature_name: internal feature key used by runner/features.
    return TASK_TYPES[feature_name]


def ensure_task_type(supabase, feature_name):
    # Keep task metadata in sync before writing any analysis_result row.
    meta = task_meta(feature_name)
    supabase.table("analysis_task_type").upsert(
        {
            "task_type": meta["task_type"],
            "task_name": meta["task_name"],
            "task_desc": meta["task_desc"],
            "is_active": True,
        },
        on_conflict="task_type",
    ).execute()
    return int(meta["task_type"])


def new_result_id():
    # The deployed schema has no result_id sequence, so generate a sortable unique id in Python.
    return time.time_ns()


def create_analysis_result(
    supabase,
    feature_name,
    time_from,
    time_to,
    target_type="global",
    target_id=None,
):
    # Every feature run starts with a metadata row shared by all result tables.
    task_type = ensure_task_type(supabase, feature_name)
    result_id = new_result_id()
    supabase.table("analysis_result").insert(
        {
            "result_id": result_id,
            "task_type": task_type,
            "target_type": target_type,
            "target_id": target_id,
            "time_from": iso(time_from),
            "time_to": iso(time_to),
        }
    ).execute()
    return result_id


def create_analysis_results(supabase, feature_name, result_specs):
    # Insert many analysis_result rows with one task metadata upsert.
    # result_specs: dicts with time_from/time_to/target_type/target_id.
    if not result_specs:
        return []

    task_type = ensure_task_type(supabase, feature_name)
    result_ids = []
    rows = []
    for spec in result_specs:
        result_id = new_result_id()
        result_ids.append(result_id)
        rows.append(
            {
                "result_id": result_id,
                "task_type": task_type,
                "target_type": spec.get("target_type", "global"),
                "target_id": spec.get("target_id"),
                "time_from": iso(spec.get("time_from")),
                "time_to": iso(spec.get("time_to")),
            }
        )

    insert_rows(supabase, "analysis_result", rows)
    return result_ids


def replace_current_result(
    supabase,
    feature_name,
    result_id,
    target_type="global",
    target_id=None,
):
    # current_analysis_result is the frontend pointer to the latest representative result.
    task_type = task_meta(feature_name)["task_type"]
    query = supabase.table("current_analysis_result").delete().eq("task_type", task_type).eq(
        "target_type", target_type
    )
    if target_type == "instance":
        query = query.eq("target_id", target_id)
    query.execute()

    supabase.table("current_analysis_result").insert(
        {
            "task_type": task_type,
            "target_type": target_type,
            "target_id": target_id,
            "result_id": result_id,
        }
    ).execute()


def replace_current_results(supabase, feature_name, current_rows):
    # Replace all frontend pointers for one feature in bulk.
    if not current_rows:
        return

    task_type = task_meta(feature_name)["task_type"]
    supabase.table("current_analysis_result").delete().eq("task_type", task_type).execute()
    insert_rows(
        supabase,
        "current_analysis_result",
        [
            {
                "task_type": task_type,
                "target_type": row.get("target_type", "global"),
                "target_id": row.get("target_id"),
                "result_id": row["result_id"],
            }
            for row in current_rows
        ],
    )


def insert_rows(supabase, table, rows):
    # Insert in chunks to avoid oversized API payloads.
    if not rows:
        return
    for start in range(0, len(rows), PAGE_SIZE):
        supabase.table(table).insert(rows[start : start + PAGE_SIZE]).execute()


def result_period_from_datetimes(values):
    # values: iterable of datetime or None values.
    dates = [value for value in values if value is not None]
    if not dates:
        now = utc_now()
        return now, now
    return min(dates), max(dates)
