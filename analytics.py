import pandas as pd
import numpy as np
import psycopg2
import psycopg2.extras
from datetime import datetime


def get_analytics(user_id: int, db_config: dict) -> dict:
    conn = psycopg2.connect(**db_config)
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT id, title, priority, status, created_at, updated_at "
        "FROM tasks WHERE user_id = %s",
        (user_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    # ── Build DataFrame ───────────────────────────────────────────────────────
    if not rows:
        return _empty_analytics()

    df = pd.DataFrame([dict(r) for r in rows])

    # Ensure proper types
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
    df["updated_at"] = pd.to_datetime(df["updated_at"], utc=True)

    # ── Core counts ──────────────────────────────────────────────────────────
    total_tasks      = int(len(df))
    completed_tasks  = int((df["status"] == "completed").sum())
    pending_tasks    = int((df["status"] == "pending").sum())
    in_progress      = int((df["status"] == "in_progress").sum())
    completion_pct   = float(np.round((completed_tasks / total_tasks) * 100, 2)) if total_tasks else 0.0

    # ── Priority breakdown ───────────────────────────────────────────────────
    priority_counts = (
        df.groupby("priority")["id"]
        .count()
        .reindex(["low", "medium", "high"], fill_value=0)
        .to_dict()
    )

    # ── Status distribution (%) ──────────────────────────────────────────────
    status_pct = (
        df["status"]
        .value_counts(normalize=True)
        .mul(100)
        .round(1)
        .to_dict()
    )

    # ── Daily task creation trend (last 14 days) ─────────────────────────────
    now = pd.Timestamp.utcnow()
    two_weeks_ago = now - pd.Timedelta(days=13)
    recent = df[df["created_at"] >= two_weeks_ago].copy()
    recent["day"] = recent["created_at"].dt.strftime("%Y-%m-%d")
    daily_series = recent.groupby("day")["id"].count()

    # Fill missing days with 0
    date_range = pd.date_range(two_weeks_ago.date(), now.date(), freq="D")
    date_index = [d.strftime("%Y-%m-%d") for d in date_range]
    daily_trend = daily_series.reindex(date_index, fill_value=0).to_dict()

    # ── Average tasks per day (NumPy) ─────────────────────────────────────────
    daily_values      = np.array(list(daily_trend.values()), dtype=float)
    avg_tasks_per_day = float(np.round(np.mean(daily_values), 2))
    peak_day_count    = int(np.max(daily_values)) if len(daily_values) else 0

    # ── Completion rate by priority ──────────────────────────────────────────
    completion_by_priority = {}
    for p in ("low", "medium", "high"):
        subset = df[df["priority"] == p]
        if len(subset):
            rate = float(np.round((subset["status"] == "completed").mean() * 100, 1))
        else:
            rate = 0.0
        completion_by_priority[p] = rate

    # ── Age of open tasks (days, NumPy stats) ────────────────────────────────
    open_tasks = df[df["status"] != "completed"]
    if len(open_tasks):
        ages = (now - open_tasks["created_at"]).dt.total_seconds() / 86400
        age_stats = {
            "mean_days":   float(np.round(np.mean(ages.values), 1)),
            "max_days":    float(np.round(np.max(ages.values),  1)),
            "median_days": float(np.round(np.median(ages.values), 1)),
        }
    else:
        age_stats = {"mean_days": 0, "max_days": 0, "median_days": 0}

    return {
        "summary": {
            "total_tasks":       total_tasks,
            "completed_tasks":   completed_tasks,
            "pending_tasks":     pending_tasks,
            "in_progress_tasks": in_progress,
            "completion_pct":    completion_pct,
        },
        "priority_breakdown":      priority_counts,
        "status_distribution_pct": status_pct,
        "daily_trend":             daily_trend,
        "avg_tasks_per_day":       avg_tasks_per_day,
        "peak_day_count":          peak_day_count,
        "completion_by_priority":  completion_by_priority,
        "open_task_age":           age_stats,
        "generated_at":            datetime.utcnow().isoformat() + "Z",
    }


def _empty_analytics() -> dict:
    return {
        "summary": {
            "total_tasks": 0, "completed_tasks": 0,
            "pending_tasks": 0, "in_progress_tasks": 0, "completion_pct": 0.0,
        },
        "priority_breakdown":      {"low": 0, "medium": 0, "high": 0},
        "status_distribution_pct": {},
        "daily_trend":             {},
        "avg_tasks_per_day":       0.0,
        "peak_day_count":          0,
        "completion_by_priority":  {"low": 0.0, "medium": 0.0, "high": 0.0},
        "open_task_age":           {"mean_days": 0, "max_days": 0, "median_days": 0},
        "generated_at":            datetime.utcnow().isoformat() + "Z",
    }
