from __future__ import annotations

from manalyzer.features.common import (
    create_analysis_result,
    fetch_all,
    insert_rows,
    parse_datetime,
    replace_current_result,
)

# from manalyzer.logger import get_logger

# logger = get_logger(__name__)


TOP_N = 50

# Each metric produces its own top-N ranking inside the same analysis result.
METRICS = [
    ("active_users", "active_users"),
    ("users", "users"),
    ("statuses", "statuses"),
    ("connections", "connections"),
]


def run(supabase):
    # logger.info("Running feature: trend_instances")
    # instances_raw is the latest public metadata snapshot for each instance.
    instances = fetch_all(
        supabase,
        "instances_raw",
        (
            "id,name,users,statuses,connections,active_users,version,topic,"
            "languages,categories,thumbnail,updated_at,checked_at,created_at,up,dead"
        ),
    )

    usable_instances = [row for row in instances if row.get("id") and row.get("name")]
    if not usable_instances:
        print("trend_instances skipped: no instances_raw rows")
        return

    dates = [
        parse_datetime(row.get("updated_at") or row.get("checked_at") or row.get("created_at"))
        for row in usable_instances
    ]
    valid_dates = [value for value in dates if value is not None]
    time_from = min(valid_dates) if valid_dates else parse_datetime(usable_instances[0].get("created_at"))
    time_to = max(valid_dates) if valid_dates else time_from
    if time_from is None or time_to is None:
        print("trend_instances skipped: no valid instance timestamps")
        return

    # Rank instances by several raw public metrics and store them in res_rank.
    result_id = create_analysis_result(
        supabase,
        "trend_instances",
        time_from=time_from,
        time_to=time_to,
    )

    rank_rows = []
    for metric_name, metric_type in METRICS:
        ranked = sorted(
            [row for row in usable_instances if row.get(metric_name) is not None],
            key=lambda row: float(row.get(metric_name) or 0),
            reverse=True,
        )[:TOP_N]

        # rank_value is the rank inside this metric_type.
        # res_rank primary key includes metric_type, so the same label/rank can appear in another metric.
        for index, row in enumerate(ranked, start=1):
            rank_rows.append(
                {
                    "result_id": result_id,
                    "rank_value": index,
                    "label": row.get("name"),
                    "instance_id": row.get("id"),
                    "amount": float(row.get(metric_name) or 0),
                    "metric_type": metric_type,
                    "extra_json": {
                        "version": row.get("version"),
                        "topic": row.get("topic"),
                        "languages": row.get("languages"),
                        "categories": row.get("categories"),
                        "thumbnail": row.get("thumbnail"),
                        "up": row.get("up"),
                        "dead": row.get("dead"),
                    },
                }
            )

    insert_rows(supabase, "res_rank", rank_rows)
    replace_current_result(supabase, "trend_instances", result_id)
