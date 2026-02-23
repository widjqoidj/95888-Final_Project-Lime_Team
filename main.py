"""
Main menu-driven CLI for Burgh Event Planner.
Recommendation logic focuses on event suggestions using price/time/date filtering.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from config import LATEST_OPTIONS_FILE, RECOMMENDATION_SAMPLE_FILE
from recommend import UserPreferences, build_event_suggestions, format_plan, score_candidates
from utils import ensure_project_directories


REQUIRED_INPUT_COLUMNS = [
    "event_name",
    "date",
    "time",
    "location",
    "price",
    "source",
    "url",
]


def _load_local_env(env_path: Path = Path(".env")) -> None:
    """Load local environment variables from .env if present."""
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _ask_float(prompt: str, default: float) -> float:
    raw = input(f"{prompt} [{default}]: ").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        print("Invalid number; using default.")
        return default


def _ask_int(prompt: str, default: int) -> int:
    raw = input(f"{prompt} [{default}]: ").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print("Invalid integer; using default.")
        return default


def _ask_optional_date(prompt: str) -> str | None:
    raw = input(prompt).strip()
    if not raw:
        return None

    parsed = pd.to_datetime(raw, errors="coerce")
    if pd.isna(parsed):
        print("Invalid date; skipping date filter.")
        return None

    return pd.Timestamp(parsed).strftime("%Y-%m-%d")


def _ensure_schema(df: pd.DataFrame) -> pd.DataFrame:
    missing_columns = [column for column in REQUIRED_INPUT_COLUMNS if column not in df.columns]
    if missing_columns:
        raise ValueError(
            "Dataset is missing required columns: "
            + ", ".join(missing_columns)
        )

    normalized = df[REQUIRED_INPUT_COLUMNS].copy()
    normalized["name"] = normalized["event_name"].fillna("").astype(str).str.strip()

    for column in ["source", "location", "price", "url", "date", "time"]:
        normalized[column] = normalized[column].fillna("").astype(str).str.strip()

    normalized = normalized[normalized["name"] != ""]
    normalized = normalized.drop(columns=["event_name"])

    normalized = normalized.drop_duplicates(
        subset=["source", "name", "date", "time", "location"]
    ).reset_index(drop=True)
    return normalized


def _load_dataset() -> tuple[Path, pd.DataFrame]:
    if not RECOMMENDATION_SAMPLE_FILE.exists():
        raise FileNotFoundError(
            f"Latest processed dataset not found: {RECOMMENDATION_SAMPLE_FILE}\n"
            "Run data collection first to generate latest event data."
        )

    df = pd.read_csv(RECOMMENDATION_SAMPLE_FILE)
    df = _ensure_schema(df)

    if LATEST_OPTIONS_FILE != RECOMMENDATION_SAMPLE_FILE:
        LATEST_OPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(LATEST_OPTIONS_FILE, index=False)

    print(f"\nLoaded event dataset: {len(df)} records")
    print(f"Working dataset source: {RECOMMENDATION_SAMPLE_FILE}")
    return LATEST_OPTIONS_FILE, df


def _print_menu() -> None:
    print("\nMenu")
    print(
        """
        1) Generate event suggestions
        2) View generated suggestions
        3) Exit
"""
    )


def _collect_preferences() -> UserPreferences:
    print("\nPlease enter your preferences:")
    budget = _ask_float("Max event budget (USD)", 75.0)
    event_date = _ask_optional_date(
        "Please enter a date (YYYY-MM-DD, leave blank for any date): "
    )
    period = input(
        "Preferred time of day (morning, afternoon, evening, any) [any]: "
    ).strip().lower()
    # Invalid period entries fall back to any for predictable behavior.
    if period not in {"morning", "afternoon", "evening", "any"}:
        if period:
            print("Invalid period; using default.")
        period = "any"
    max_results = _ask_int("Number of suggestions to generate", 3)

    return UserPreferences(
        budget=max(0.0, budget),
        preferred_period=period,
        max_results=max(1, max_results),
        event_date=event_date,
    )


def _print_generated_plans(generated_plans: list[dict]) -> None:
    if not generated_plans:
        print("\nNo generated suggestions available. Choose option 1 first.")
        return

    print("\nTop Event Suggestions")
    print("---------------------")
    for i, plan in enumerate(generated_plans, start=1):
        print(format_plan(plan, i))
        print()


def main() -> None:
    ensure_project_directories()
    _load_local_env()

    print("=" * 30)
    print("Welcome to Burgh Event Planner")
    print("=" * 30)
    print("Loading latest event dataset...\n")

    _, df = _load_dataset()
    generated_plans: list[dict] = []

    while True:
        _print_menu()
        choice = input("Choose an option: ").strip()

        if choice == "1":
            prefs = _collect_preferences()
            scored = score_candidates(df, prefs)
            generated_plans = build_event_suggestions(scored, prefs)
            if not generated_plans:
                print(
                    "\nNo suggestions matched current constraints. "
                    "Try a different date, period, or higher budget."
                )
                continue

            print(f"\nGenerated {len(generated_plans)} suggestion(s).\n")

        elif choice == "2":
            _print_generated_plans(generated_plans)

        elif choice == "3":
            print("\nExiting Burgh Event Planner.")
            break

        else:
            print("\nInvalid option. Please try again.")


if __name__ == "__main__":
    main()
