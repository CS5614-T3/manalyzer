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


TOP_N = 30

# Each tuple is (task_name, metric_name, period_days).
RANK_SPECS = [
    ("trending_hashtag_uses_1d", "uses", 1),
    ("trending_hashtag_uses_7d", "uses", 7),
    ("trending_hashtag_uses_30d", "uses", 30),
    ("trending_hashtag_accounts_1d", "accounts", 1),
    ("trending_hashtag_accounts_7d", "accounts", 7),
    ("trending_hashtag_accounts_30d", "accounts", 30),
]


def day_start(value):
    # value: parsed trend history timestamp
    # Normalize trend days to UTC midnight for date-window comparisons.
    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)


def build_joined_rows(trends, history, instances):
    # trends/history/instances: raw rows from Supabase tables
    # trend_by_id lets history rows find their hashtag metadata.
    trend_by_id = {row.get("id"): row for row in trends if row.get("id")}

    # instance_id_by_name maps trends_raw.base_url to instances_raw.id.
    instance_id_by_name = {row.get("name"): row.get("id") for row in instances if row.get("name")}

    # joined_rows: normalized trend events with instance_id, label, day, uses, and accounts.
    joined_rows = []
    for row in history:
        trend = trend_by_id.get(row.get("trend_id"))
        if trend is None:
            continue

        base_url = trend.get("base_url")
        instance_id = instance_id_by_name.get(base_url)
        day = parse_datetime(row.get("day"))
        label = trend.get("name") or row.get("trend_id")
        if not instance_id or day is None or not label:
            continue

        joined_rows.append(
            {
                "instance_id": instance_id,
                "base_url": base_url,
                "label": label,
                "trend_id": row.get("trend_id"),
                "day": day_start(day),
                "uses": float(row.get("uses") or 0),
                "accounts": float(row.get("accounts") or 0),
            }
        )
    return joined_rows


def build_rank_rows(joined_rows, instance_id, metric_name, period_start, period_end, result_id):
    # stats_by_label accumulates one metric inside the selected date window.
    # If instance_id is None, aggregate all servers into one global ranking.
    stats_by_label = defaultdict(lambda: {"amount": 0.0, "trend_ids": set(), "base_urls": set()})

    for row in joined_rows:
        if instance_id is not None and row["instance_id"] != instance_id:
            continue
        if not (period_start <= row["day"] < period_end):
            continue

        stats = stats_by_label[row["label"]]
        stats["amount"] += row[metric_name]
        stats["trend_ids"].add(row["trend_id"])
        stats["base_urls"].add(row["base_url"])

    # ranked keeps only the top hashtags for this instance/metric/window.
    ranked = sorted(stats_by_label.items(), key=lambda item: item[1]["amount"], reverse=True)[:TOP_N]
    return [
        {
            "result_id": result_id,
            "rank_value": index,
            "label": label,
            "instance_id": instance_id,
            "amount": stats["amount"],
            "metric_type": metric_name,
            "extra_json": {
                "period_days": (period_end - period_start).days,
                "trend_ids": sorted(value for value in stats["trend_ids"] if value),
                "base_urls": sorted(value for value in stats["base_urls"] if value),
            },
        }
        for index, (label, stats) in enumerate(ranked, start=1)
    ]


def write_rank_result(supabase, task_name, joined_rows, instance_id, metric_name, analysis_day, period_days):
    # period_end is exclusive, so a 1-day window covers exactly analysis_day.
    period_end = analysis_day + timedelta(days=1)
    period_start = period_end - timedelta(days=period_days)
    target_type = "global" if instance_id is None else "instance"

    result_id = create_analysis_result(
        supabase,
        task_name,
        time_from=period_start,
        time_to=period_end - timedelta(seconds=1),
        target_type=target_type,
        target_id=instance_id,
    )

    rank_rows = build_rank_rows(
        joined_rows,
        instance_id,
        metric_name,
        period_start,
        period_end,
        result_id,
    )
    insert_rows(supabase, "res_rank", rank_rows)
    replace_current_result(supabase, task_name, result_id, target_type=target_type, target_id=instance_id)


def run(supabase):
    # logger.info("Running feature: trending_hashtag")
    # Load hashtag metadata, metric history, and instance ids for joining.
    trends = fetch_all(supabase, "trends_raw", "id,name,base_url")
    history = fetch_all(supabase, "trends_history_raw", "day,uses,accounts,trend_id", order="day")
    instances = fetch_all(supabase, "instances_raw", "id,name")

    joined_rows = build_joined_rows(trends, history, instances)
    if not joined_rows:
        print("trending_hashtag skipped: no joined trend history rows")
        return

    # analysis_day is the most recent trend day available in the collected data.
    analysis_day = max(row["day"] for row in joined_rows)

    # Create global rankings first by aggregating all instances together.
    for task_name, metric_name, period_days in RANK_SPECS:
        write_rank_result(
            supabase,
            task_name,
            joined_rows,
            None,
            metric_name,
            analysis_day,
            period_days,
        )

    # Then create per-instance rankings for servers that have joined trend events.
    instance_ids = sorted({row["instance_id"] for row in joined_rows})

    for instance_id in instance_ids:
        for task_name, metric_name, period_days in RANK_SPECS:
            write_rank_result(
                supabase,
                task_name,
                joined_rows,
                instance_id,
                metric_name,
                analysis_day,
                period_days,
            )
