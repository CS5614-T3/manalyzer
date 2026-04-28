from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from manalyzer.features.common import (
    create_analysis_result,
    fetch_all,
    insert_rows,
    parse_date,
    parse_datetime,
    replace_current_result,
    safe_ratio,
)

# from manalyzer.logger import get_logger

# logger = get_logger(__name__)


def run(supabase):
    # logger.info("Running feature: compare_servers")
    # Combine instance metadata, activity history, and trend history into comparable metrics.
    instances = fetch_all(
        supabase,
        "instances_raw",
        "id,name,users,statuses,active_users,updated_at,checked_at,created_at",
    )
    activity_rows = fetch_all(supabase, "activity_raw", "base_url,week,statuses")
    trends = fetch_all(supabase, "trends_raw", "id,base_url")
    history = fetch_all(supabase, "trends_history_raw", "trend_id,uses,accounts,day")

    usable_instances = [row for row in instances if row.get("id") and row.get("name")]
    if not usable_instances:
        print("compare_servers skipped: no instances_raw rows")
        return

    # activity_statuses: {base_url: total statuses from activity_raw}
    activity_statuses = defaultdict(float)

    # activity_weeks: {base_url: set of weeks that have activity data}
    activity_weeks = defaultdict(set)
    period_values = []
    # activity_raw is keyed by instance domain, matching instances_raw.name.
    for row in activity_rows:
        base_url = row.get("base_url")
        week = parse_date(row.get("week"))
        if not base_url or week is None:
            continue
        activity_statuses[base_url] += float(row.get("statuses") or 0)
        activity_weeks[base_url].add(week)
        period_values.append(datetime(week.year, week.month, week.day, tzinfo=timezone.utc))

    trend_base_url_by_id = {row.get("id"): row.get("base_url") for row in trends if row.get("id")}
    # trend_uses/trend_accounts: totals by source instance domain.
    trend_uses = defaultdict(float)
    trend_accounts = defaultdict(float)
    # Convert hashtag trend rows back to their source instance domain.
    for row in history:
        base_url = trend_base_url_by_id.get(row.get("trend_id"))
        if not base_url:
            continue
        trend_uses[base_url] += float(row.get("uses") or 0)
        trend_accounts[base_url] += float(row.get("accounts") or 0)
        day = parse_datetime(row.get("day"))
        if day is not None:
            period_values.append(day)

    for row in usable_instances:
        checked = parse_datetime(row.get("checked_at") or row.get("updated_at") or row.get("created_at"))
        if checked is not None:
            period_values.append(checked)

    if not period_values:
        print("compare_servers skipped: no valid timestamps")
        return

    result_id = create_analysis_result(
        supabase,
        "compare_servers",
        time_from=min(period_values),
        time_to=max(period_values),
    )

    result_rows = []
    for row in usable_instances:
        base_url = row.get("name")
        week_count = len(activity_weeks.get(base_url, set()))
        posts_per_day = None
        if week_count > 0:
            posts_per_day = activity_statuses[base_url] / (week_count * 7)

        # res_instance stores one comparable metric row per instance.
        result_rows.append(
            {
                "result_id": result_id,
                "instance_id": row.get("id"),
                "user_count": row.get("users"),
                "activity": safe_ratio(row.get("active_users"), row.get("users")),
                "trend_activity": safe_ratio(trend_uses.get(base_url), trend_accounts.get(base_url)),
                "posts_per_day": posts_per_day,
            }
        )

    insert_rows(supabase, "res_instance", result_rows)
    replace_current_result(supabase, "compare_servers", result_id)
