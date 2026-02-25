"""
Burgh Event Planner

This file contains:
- Original command line interface (dishengl)
- Web application wrapper (knorris2)
- Shared "core" wrappers are used by command line and web interfaces:
    1) load_events_df()
    2) generate_suggestions(df, prefs)
"""

from __future__ import annotations

# imports

import os
from pathlib import Path

import pandas as pd
from flask import Flask, render_template, request, redirect, session, url_for

from config import LATEST_OPTIONS_FILE, RECOMMENDATION_SAMPLE_FILE
from recommend import UserPreferences, build_event_suggestions, format_plan, score_candidates
from utils import ensure_project_directories



# Original command line interface (dishengl)

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


def _ensure_schema(df: pd.DataFrame) -> pd.DataFrame:
    missing_columns = [column for column in REQUIRED_INPUT_COLUMNS if column not in df.columns]
    if missing_columns:
        raise ValueError("Dataset is missing required columns: " + ", ".join(missing_columns))

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


# web-friendly wrappers (knorris2)

def load_events_df() -> pd.DataFrame:
    ensure_project_directories()
    _load_local_env()
    _, df = _load_dataset()
    return df


def generate_suggestions(df: pd.DataFrame, prefs: UserPreferences) -> list[dict]:
    scored = score_candidates(df, prefs)
    return build_event_suggestions(scored, prefs)



# Original command line interface (dishengl)

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


def main_cli() -> None:
    print("=" * 30)
    print("Welcome to Burgh Event Planner")
    print("=" * 30)
    print("Loading latest event dataset...\n")

    df = load_events_df()
    generated_plans: list[dict] = []

    while True:
        _print_menu()
        choice = input("Choose an option: ").strip()

        if choice == "1":
            prefs = _collect_preferences()
            generated_plans = generate_suggestions(df, prefs)

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


# Web application (knorris2)

app = Flask(__name__)
app.secret_key = "dev-secret-change-me"  

_EVENTS_DF: pd.DataFrame | None = None
_LOAD_ERROR: str | None = None


def get_cached_df() -> pd.DataFrame | None:
    global _EVENTS_DF, _LOAD_ERROR
    if _EVENTS_DF is not None or _LOAD_ERROR is not None:
        return _EVENTS_DF
    try:
        _EVENTS_DF = load_events_df()
        _LOAD_ERROR = None
    except Exception as exc:
        _EVENTS_DF = None
        _LOAD_ERROR = str(exc)
    return _EVENTS_DF


def prefs_from_session() -> UserPreferences:
    return UserPreferences(
        budget=float(session.get("budget", 75.0)),
        preferred_period=str(session.get("preferred_period", "any")),
        max_results=int(session.get("max_results", 3)),
        event_date=(session.get("event_date") or None) or None,
    )


@app.get("/healthz")
def healthz():
    return "ok", 200


@app.route("/")
def web_menu():
    get_cached_df()
    message = session.pop("message", None)
    if _LOAD_ERROR:
        message = f"Dataset load error: {_LOAD_ERROR}"
    return render_template("menu.html", message=message)


@app.route("/wizard/budget", methods=["GET", "POST"])
def wizard_budget():
    if request.method == "POST":
        raw = (request.form.get("value") or "").strip()
        try:
            budget = float(raw) if raw else 75.0
        except ValueError:
            return render_template(
                "step.html",
                title="Max event budget (USD)",
                help_text="Enter a number (default 75.0).",
                input_type="number",
                step="0.01",
                min="0",
                default="75.0",
                error="Invalid number.",
            )

        session["budget"] = max(0.0, budget)
        return redirect(url_for("wizard_date"))

    return render_template(
        "step.html",
        title="Max event budget (USD)",
        help_text="Default is 75.0",
        input_type="number",
        step="0.01",
        min="0",
        default=str(session.get("budget", 75.0)),
        placeholder="75.00",
    )


@app.route("/wizard/date", methods=["GET", "POST"])
def wizard_date():
    if request.method == "POST":
        raw = (request.form.get("value") or "").strip()
        if not raw:
            session["event_date"] = ""
            return redirect(url_for("wizard_period"))

        parsed = pd.to_datetime(raw, errors="coerce")
        if pd.isna(parsed):
            return render_template(
                "step.html",
                title="Event date (Optional)",
                help_text="Pick a date in the next 10 days or leave blank for any date.",
                input_type="date",
                default=session.get("event_date", ""),
                error="Invalid date; try again or leave blank.",
            )

        session["event_date"] = pd.Timestamp(parsed).strftime("%Y-%m-%d")
        return redirect(url_for("wizard_period"))

    return render_template(
        "step.html",
        title="Event date (optional)",
        help_text="Pick a date in the next 10 days or leave blank for any date.",
        input_type="date",
        default=session.get("event_date", ""),
    )


@app.route("/wizard/period", methods=["GET", "POST"])
def wizard_period():
    if request.method == "POST":
        period = (request.form.get("value") or "any").strip().lower()
        if period not in {"morning", "afternoon", "evening", "any"}:
            period = "any"
        session["preferred_period"] = period
        return redirect(url_for("wizard_max_results"))

    options = [
        {"value": "any", "label": "Any"},
        {"value": "morning", "label": "Morning"},
        {"value": "afternoon", "label": "Afternoon"},
        {"value": "evening", "label": "Evening"},
    ]

    return render_template(
        "step.html",
        title="Preferred time of day",
        help_text="Choose morning, afternoon, evening, or any.",
        input_type="select",
        options=options,
        default=session.get("preferred_period", "any"),
    )


@app.route("/wizard/max-results", methods=["GET", "POST"])
def wizard_max_results():
    if request.method == "POST":
        raw = (request.form.get("value") or "").strip()
        try:
            max_results = int(raw) if raw else 3
        except ValueError:
            return render_template(
                "step.html",
                title="Number of suggestions to generate",
                help_text="Enter an integer (default 3).",
                input_type="number",
                min="1",
                step="1",
                default=str(session.get("max_results", 3)),
                error="Invalid integer.",
            )

        session["max_results"] = max(1, max_results)
        return redirect(url_for("wizard_generate"))

    return render_template(
        "step.html",
        title="Number of suggestions to generate",
        help_text="Default is 3",
        input_type="number",
        min="1",
        step="1",
        default=str(session.get("max_results", 3)),
    )


@app.route("/wizard/generate")
def wizard_generate():
    df = get_cached_df()
    if df is None:
        session["message"] = f"Dataset is not available yet: {_LOAD_ERROR}"
        return redirect(url_for("web_menu"))

    prefs = prefs_from_session()
    plans = generate_suggestions(df, prefs)
    session["generated_plans"] = plans

    if not plans:
        session["message"] = (
            "No suggestions matched current constraints. "
            "Try a different date, period, or higher budget."
        )
        return redirect(url_for("web_menu"))

    return redirect(url_for("suggestions"))


@app.route("/suggestions")
def suggestions():
    plans = session.get("generated_plans", [])
    return render_template("suggestions.html", plans=plans)


@app.route("/exit")
def exit_app():
    session.clear()
    return render_template("menu.html", message="Session cleared. (This is the web version of Exit.)")


if __name__ == "__main__":
    app.run(debug=True)
    # To run the command line locally, comment the line above and run:
    # main_cli()