"""
Recommendation helpers for general event suggestions.
Filter and rank events by time of day, date, and price.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass
class UserPreferences:
    budget: float
    preferred_period: str = "any"
    max_results: int = 5
    min_price: float = 0.0
    event_date: str | None = None


PERIODS = ("morning", "afternoon", "evening")
VALID_PERIODS = PERIODS + ("any",)
PERIOD_INDEX = {period: index for index, period in enumerate(PERIODS)}


def _normalize_period(value: Any, default: str = "any") -> str:
    text = str(value or "").strip().lower()
    if text in VALID_PERIODS:
        return text
    return default


def _normalize_event_date(value: Any) -> pd.Timestamp | None:
    text = str(value or "").strip()
    if not text:
        return None

    timestamp = pd.to_datetime(text, errors="coerce")
    if pd.isna(timestamp):
        return None

    return pd.Timestamp(timestamp).normalize()


def _hour_to_period(hour: int) -> str:
    # Bucket hours into coarse periods used by both filtering and scoring.
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
    2) filter by price, preferred period of day, and optional date
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
        suggestions.append(
            {
                "plan_name": f"Event Suggestion #{index}",
                "total_estimated_cost": round(float(row.get("estimated_cost", 0.0) or 0.0), 2),
                "score": round(float(row.get("overall_score", 0.0) or 0.0), 4),
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
