"""
Recommendation helpers for general event suggestions.
Filter and rank events by time of day, date, and price.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

import pandas as pd


@dataclass
class UserPreferences:
    budget: float
    preferred_period: str = "any"
    max_results: int = 5
    min_price: float = 0.0
    event_date: str | None = None
    # If False, date matching stays strict and no flexible date backfill is attempted.
    allow_flexible_dates: bool = False


PERIODS = ("morning", "afternoon", "evening")
# "any" is a bypass sentinel used by CLI and scoring to disable period filtering.
VALID_PERIODS = PERIODS + ("any",)
PERIOD_INDEX = {period: index for index, period in enumerate(PERIODS)}

MATCH_LEVEL_EXACT = "exact"
MATCH_LEVEL_FLEXIBLE_PERIOD = "flexible_period"
MATCH_LEVEL_FLEXIBLE_DATE = "flexible_date"
MATCH_LEVEL_FLEXIBLE_PERIOD_AND_DATE = "flexible_period_and_date"

MATCH_LEVEL_PRIORITY = {
    MATCH_LEVEL_EXACT: 0,
    MATCH_LEVEL_FLEXIBLE_PERIOD: 1,
    MATCH_LEVEL_FLEXIBLE_DATE: 2,
    MATCH_LEVEL_FLEXIBLE_PERIOD_AND_DATE: 3,
}

MATCH_LEVEL_LABEL = {
    MATCH_LEVEL_EXACT: "Exact match",
    MATCH_LEVEL_FLEXIBLE_PERIOD: "Flexible match (time flexible)",
    MATCH_LEVEL_FLEXIBLE_DATE: "Flexible match (date flexible)",
    MATCH_LEVEL_FLEXIBLE_PERIOD_AND_DATE: "Flexible match (date and time flexible)",
}

FLEXIBLE_DATE_WINDOW_DAYS = 3


def _normalize_period(value: Any, default: str = "any") -> str:
    text = str(value or "").strip().lower()
    if text in VALID_PERIODS:
        return text
    return default


def _normalize_event_date(value: Any) -> pd.Timestamp | None:
    text = str(value or "").strip()
    if not text:
        return None

    # Accept flexible input (e.g. "2026-02-23", "Feb 23 2026") and collapse to date-only.
    timestamp = pd.to_datetime(text, errors="coerce")
    if pd.isna(timestamp):
        return None

    return pd.Timestamp(timestamp).normalize()


def _hour_to_period(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    return "evening"


def _parse_price_text(value: Any) -> float:
    if value is None or pd.isna(value):
        return 0.0

    text = str(value).strip()
    if not text or text.upper() == "N/A":
        return 0.0
    if "free" in text.lower():
        return 0.0

    numbers = [float(num) for num in re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))]
    if not numbers:
        return 0.0

    if len(numbers) >= 2 and ("-" in text or " to " in text.lower()):
        # Use the midpoint when a range like "$10-$20" is given.
        return round((numbers[0] + numbers[1]) / 2, 2)
    return numbers[0]


def _coerce_start_time(df: pd.DataFrame) -> pd.Series:
    # Source data stores date and time separately, here we synthesize a single timestamp.
    date_text = df["date"].fillna("").astype(str).str.strip()
    time_text = df["time"].fillna("").astype(str).str.strip()

    combined = pd.to_datetime(
        (date_text + " " + time_text).str.strip(),
        errors="coerce",
    )
    date_only = pd.to_datetime(date_text, errors="coerce")

    return combined.fillna(date_only)


def _prepare_candidates(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    required_columns = ["name", "date", "time", "location", "price", "source", "url"]
    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        raise ValueError(
            "Recommendation input is missing required columns: "
            + ", ".join(missing_columns)
        )

    prepared = df[required_columns].copy()

    for column in required_columns:
        if column != "price":
            prepared[column] = prepared[column].fillna("").astype(str).str.strip()

    prepared["estimated_cost"] = prepared["price"].apply(_parse_price_text)

    prepared["start_time"] = _coerce_start_time(prepared)
    prepared["name"] = prepared["name"].fillna("").astype(str)
    prepared = prepared[prepared["name"].str.strip() != ""]

    # Deduplicate repeated listings from different scrape passes.
    prepared = prepared.drop_duplicates(
        subset=["source", "name", "date", "time", "location"]
    ).reset_index(drop=True)
    return prepared


def filter_by_price(df: pd.DataFrame, min_price: float = 0.0, max_price: float = 0.0) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    if min_price <= 0 and max_price <= 0:
        return df.copy()

    price = pd.to_numeric(df["estimated_cost"], errors="coerce").fillna(0.0)
    mask = pd.Series(True, index=df.index)

    if min_price > 0:
        mask &= price >= min_price
    if max_price > 0:
        mask &= price <= max_price

    return df[mask].copy().reset_index(drop=True)


def filter_by_time_period(
    df: pd.DataFrame,
    preferred_period: str,
) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    target_period = _normalize_period(preferred_period)
    if target_period == "any":
        # Keep full result set when user does not want time-of-day constraints.
        return df.copy().reset_index(drop=True)

    timestamps = pd.to_datetime(df["start_time"], errors="coerce")
    in_period = timestamps.apply(
        lambda ts: _hour_to_period(int(ts.hour)) == target_period if pd.notna(ts) else False
    )

    return df[in_period].copy().reset_index(drop=True)


def filter_by_event_date(
    df: pd.DataFrame,
    event_date: Any = None,
) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    target_date = _normalize_event_date(event_date)
    if target_date is None:
        return df.copy()

    timestamps = pd.to_datetime(df["start_time"], errors="coerce")
    # Compare at day granularity so HH:MM differences do not exclude valid same-day events.
    on_target_date = timestamps.dt.normalize() == target_date
    return df[on_target_date].copy().reset_index(drop=True)


def _budget_score(cost: float, budget: float) -> float:
    # Piecewise penalty: within budget scores highest, modest overages are tolerated.
    if budget <= 0:
        return 0.7
    if cost <= budget:
        return max(0.4, 1 - (cost / max(budget, 1e-9)) * 0.6)

    over_ratio = (cost - budget) / max(budget, 1e-9)
    if over_ratio <= 0.1:
        return 0.2
    if over_ratio <= 0.25:
        return 0.1
    return 0.0


def _time_score(timestamp: Any, prefs: UserPreferences) -> float:
    preferred_period = _normalize_period(prefs.preferred_period)
    if preferred_period == "any":
        # Neutral/full credit when user has no time-of-day preference.
        return 1.0

    if pd.isna(timestamp):
        return 0.2

    event_period = _hour_to_period(int(pd.Timestamp(timestamp).hour))
    # Neighbor periods are partially acceptable; opposite period gets lowest score.
    distance = abs(PERIOD_INDEX[event_period] - PERIOD_INDEX[preferred_period])

    if distance == 0:
        return 1.0
    if distance == 1:
        return 0.55
    return 0.25


def score_candidates(df: pd.DataFrame, prefs: UserPreferences) -> pd.DataFrame:
    """
    Key recommendation flow:
    1) normalize candidate fields
    2) filter by price, preferred period of day, and date (optional, if user specified)
    3) score remaining events
    """
    prepared = _prepare_candidates(df)
    if prepared.empty:
        return prepared

    preferred_period = _normalize_period(prefs.preferred_period)

    filtered = filter_by_price(
        prepared,
        min_price=max(0.0, prefs.min_price),
        max_price=max(0.0, prefs.budget),
    )
    filtered = filter_by_time_period(
        filtered,
        preferred_period,
    )
    filtered = filter_by_event_date(
        filtered,
        prefs.event_date,
    )

    if filtered.empty:
        return filtered

    scored = filtered.copy()

    scored["price_score"] = scored["estimated_cost"].fillna(0.0).apply(
        lambda value: _budget_score(float(value), prefs.budget)
    )
    scored["time_score"] = scored["start_time"].apply(lambda value: _time_score(value, prefs))
    scored["overall_score"] = (
        scored["price_score"] * 0.55
        + scored["time_score"] * 0.45
    )

    return scored.sort_values(
        by=["overall_score", "time_score"],
        ascending=[False, False],
    ).reset_index(drop=True)


def _candidate_identity(row: pd.Series) -> tuple[str, str, str, str, str]:
    # Stable event identity used to deduplicate items that can reappear across stages.
    return (
        str(row.get("source", "")).strip().lower(),
        str(row.get("name", "")).strip().lower(),
        str(row.get("date", "")).strip(),
        str(row.get("time", "")).strip(),
        str(row.get("location", "")).strip().lower(),
    )


def _build_flexible_filter_stages(prefs: UserPreferences) -> list[tuple[str, UserPreferences]]:
    """
    Build ordered scoring stages:
    1) exact filters
    2) flexible period only (if period is constrained)
    3) flexible date only (only when flexible dates is enabled)
    4) flexible period and date (only when flexible dates is enabled)
    """
    stages = [(MATCH_LEVEL_EXACT, prefs)]
    has_period_filter = _normalize_period(prefs.preferred_period) != "any"
    has_date_filter = _normalize_event_date(prefs.event_date) is not None

    if has_period_filter:
        stages.append(
            (
                MATCH_LEVEL_FLEXIBLE_PERIOD,
                replace(prefs, preferred_period="any"),
            )
        )

    if has_date_filter and prefs.allow_flexible_dates:
        stages.append(
            (
                MATCH_LEVEL_FLEXIBLE_DATE,
                replace(prefs, event_date=None),
            )
        )

    if has_period_filter and has_date_filter and prefs.allow_flexible_dates:
        stages.append(
            (
                MATCH_LEVEL_FLEXIBLE_PERIOD_AND_DATE,
                replace(prefs, preferred_period="any", event_date=None),
            )
        )

    return stages


def _filter_to_nearby_dates(
    scored_df: pd.DataFrame,
    target_date: pd.Timestamp | None,
    max_distance_days: int = FLEXIBLE_DATE_WINDOW_DAYS,
) -> pd.DataFrame:
    # Keep flexible-date results within a bounded window around the requested day.
    if scored_df.empty or target_date is None:
        return scored_df.copy()

    filtered = scored_df.copy()
    event_days = pd.to_datetime(filtered["start_time"], errors="coerce").dt.normalize()
    date_distance_days = (event_days - target_date).abs().dt.days
    filtered["_date_distance_days"] = date_distance_days

    nearby_only = (
        filtered["_date_distance_days"].notna()
        & (filtered["_date_distance_days"] <= max_distance_days)
    )
    return filtered[nearby_only].copy().reset_index(drop=True)


def _apply_stage_specific_filters(
    scored_df: pd.DataFrame,
    stage_level: str,
    user_prefs: UserPreferences,
) -> pd.DataFrame:
    # Only flexible-date stages use a nearby-date window; other stages keep full stage output.
    if stage_level not in {MATCH_LEVEL_FLEXIBLE_DATE, MATCH_LEVEL_FLEXIBLE_PERIOD_AND_DATE}:
        return scored_df

    target_date = _normalize_event_date(user_prefs.event_date)
    return _filter_to_nearby_dates(scored_df, target_date)


def select_ranked_candidates_with_flexible_filters(
    df: pd.DataFrame,
    prefs: UserPreferences,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """
    Return up to prefs.max_results by prioritizing strict matches first, then
    progressively applying flexible period/date filters when needed.
    """
    target = max(1, int(prefs.max_results))
    selected_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    exact_available = 0

    for level, stage_prefs in _build_flexible_filter_stages(prefs):
        scored = score_candidates(df, stage_prefs)
        scored = _apply_stage_specific_filters(scored, level, prefs)
        if level == MATCH_LEVEL_EXACT:
            exact_available = len(scored)
        if scored.empty:
            continue

        for _, row in scored.iterrows():
            identity = _candidate_identity(row)
            if identity in seen:
                continue

            row_dict = row.to_dict()
            # Track the stage that contributed this row for summary/ordering.
            row_dict["_match_level"] = level
            selected_rows.append(row_dict)
            seen.add(identity)

            if len(selected_rows) >= target:
                break

        if len(selected_rows) >= target:
            break

    if not selected_rows:
        return pd.DataFrame(), {
            "requested": target,
            "returned": 0,
            "exact_available": exact_available,
            "exact_returned": 0,
            "flexible_returned": 0,
        }

    selected = pd.DataFrame(selected_rows)
    selected["_match_priority"] = selected["_match_level"].map(MATCH_LEVEL_PRIORITY).fillna(99)
    if "_date_distance_days" in selected.columns:
        date_distance_series = pd.to_numeric(selected["_date_distance_days"], errors="coerce")
    else:
        # Exact/period-flexible stages do not create date distance; treat as 0 for sorting.
        date_distance_series = pd.Series(0, index=selected.index, dtype="float64")

    # Sort by stage strictness first, then by date proximity, then recommendation score.
    selected["_date_distance_sort"] = date_distance_series.fillna(0).astype(int)
    selected = selected.sort_values(
        by=["_match_priority", "_date_distance_sort", "overall_score", "time_score"],
        ascending=[True, True, False, False],
    ).head(target).reset_index(drop=True)

    exact_returned = int((selected["_match_level"] == MATCH_LEVEL_EXACT).sum())
    returned = len(selected)

    return selected, {
        "requested": target,
        "returned": returned,
        "exact_available": exact_available,
        "exact_returned": exact_returned,
        "flexible_returned": returned - exact_returned,
    }


def _row_to_stop(row: pd.Series) -> dict[str, Any]:
    timestamp = row["start_time"]
    start_time = ""
    if pd.notna(timestamp):
        start_time = pd.Timestamp(timestamp).strftime("%Y-%m-%d %H:%M")

    return {
        "name": str(row["name"]),
        "category": "event",
        "location": str(row["location"]),
        "estimated_cost": float(row["estimated_cost"] or 0.0),
        "source": str(row["source"]),
        "start_time": start_time,
        "url": str(row["url"]),
    }


def build_event_suggestions(scored_df: pd.DataFrame, prefs: UserPreferences) -> list[dict[str, Any]]:
    if scored_df.empty:
        return []

    top = scored_df.head(max(1, prefs.max_results)).copy()
    suggestions: list[dict[str, Any]] = []

    for index, (_, row) in enumerate(top.iterrows(), start=1):
        stop = _row_to_stop(row)
        match_level = str(row.get("_match_level", MATCH_LEVEL_EXACT))
        suggestions.append(
            {
                "plan_name": f"Event Suggestion #{index}",
                "total_estimated_cost": round(float(row.get("estimated_cost", 0.0) or 0.0), 2),
                "score": round(float(row.get("overall_score", 0.0) or 0.0), 4),
                "match_level": match_level,
                "match_label": MATCH_LEVEL_LABEL.get(match_level, MATCH_LEVEL_LABEL[MATCH_LEVEL_EXACT]),
                "stops": [stop],
                "backup_idea": "",
            }
        )

    return suggestions


def plans_to_dataframe(plans: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for plan in plans:
        stops = plan.get("stops", [])
        stop_text = " | ".join(
            f"{stop.get('name')} ({stop.get('category')}, ${stop.get('estimated_cost', 0):.0f})"
            for stop in stops
        )
        rows.append(
            {
                "suggestion_name": plan.get("plan_name", ""),
                "estimated_cost": plan.get("total_estimated_cost", 0.0),
                "score": plan.get("score", 0.0),
                "stops": stop_text,
            }
        )
    return pd.DataFrame(rows)


def format_plan(plan: dict[str, Any], index: int) -> str:
    lines = [
        f"{index}. {plan.get('plan_name', 'Event Suggestion')}",
        f"   Estimated price: ${plan.get('total_estimated_cost', 0.0):.2f}",
    ]

    for stop in plan.get("stops", []):
        when = f" @ {stop.get('start_time')}" if stop.get("start_time") else ""
        lines.append(
            "   - "
            f"{stop.get('name')} [{stop.get('category')}] "
            f"${stop.get('estimated_cost', 0.0):.2f}{when}"
        )
        if stop.get("location"):
            lines.append(f"     Location: {stop.get('location')}")
        if stop.get("source"):
            lines.append(f"     Source: {stop.get('source')}")
        if stop.get("url"):
            lines.append(f"     Link: {stop.get('url')}")

    return "\n".join(lines)
