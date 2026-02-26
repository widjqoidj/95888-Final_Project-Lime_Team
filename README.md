# Burgh Event Planner

Team Name: Lime Team  
Group Members (Andrew IDs):
- Disheng Lu (`dishengl`)
- Katerina Hrisopoulos (`khrisopo`)
- Kimberly Norris (`knorris2`)

## Product Vision
Help users quickly find relevant Pittsburgh events based on budget, date, and time-of-day preferences.
A demo version of the app can be found at https://event-finder-g7hz.onrender.com/ 

## Overview
This project scrapes event listings, cleans them into a local CSV, and generates ranked event suggestions through:
- a Flask web app (default runtime)
- a CLI flow (available in `main.py`)

## Data Sources
- Eventbrite Pittsburgh: `https://www.eventbrite.com/d/pa--pittsburgh/all-events/`
- PGH.Events: `https://pgh.events/`

Source configuration lives in `config.py`.

## Tech Stack
- Python 3.11+ (runtime target in `runtime.txt`)
- `requests`, `beautifulsoup4`, `pandas`
- `flask` (web app), `gunicorn` (production server option)

## Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run the Project

### 1) Refresh event data
```bash
python3 data_collection.py
```
This updates `data/pittsburgh_events.csv`.

### 2) Start the web app (default)
```bash
python3 main.py
```
Then open:
- `http://127.0.0.1:5000/`

Optional health check:
- `http://127.0.0.1:5000/healthz`

### 3) Optional production-style run
```bash
gunicorn main:app
```

### 4) Optional CLI mode
`main.py` currently starts the Flask app by default.  
To run CLI mode, switch the bottom entrypoint in `main.py` from `app.run(...)` to `main_cli()`.

## Web Wizard Flow
The web flow (`/wizard/...`) collects preferences in this order:
1. Max budget
2. Event date
3. Preferred time of day
4. Number of suggestions

Date step behavior:
- If no date is provided, date filtering is skipped.
- If a date is provided and `Flexible dates` is unchecked, matching is strict by that date.
- If a date is provided and `Flexible dates` is checked, nearby dates can be used when exact-date matches are insufficient.

Suggestions page shows a summary line like:
- `Requested 5, showing 5. 2 exact match(es) and 3 nearby match(es) were used.`

## Recommendation Logic (`recommend.py`)
Core logic:
1. Validate required columns and normalize event rows.
2. Parse price text into numeric estimated cost.
3. Build a unified `start_time` from `date` + `time`.
4. Apply strict filters (budget, period, optional date).
5. Score candidates (`price_score` 55%, `time_score` 45%).
6. If needed, backfill via staged flexible filtering:
   - exact filters
   - flexible period
   - flexible date (only when `Flexible dates` is enabled)
   - flexible period + date (only when `Flexible dates` is enabled)
7. For flexible-date stages, candidates are limited to a nearby date window (`±3` days).

## Data Schema
`main.py` expects these required input columns from the processed CSV:
- `event_name`
- `date`
- `time`
- `location`
- `price`
- `source`
- `url`

Extra columns are allowed.

## Project Structure
```text
.
├── main.py
├── config.py
├── data_collection.py
├── recommend.py
├── utils.py
├── requirements.txt
├── runtime.txt
├── templates/
    └── index.html
├── static/
└── data/
    └── pittsburgh_events.csv
```

## GenAI Use
- Model: ChatGPT-5.3-Codex
- Use cases:
  - Integration and refactoring support
  - Configuration and utility setup
  - Recommendation logic improvements and validation
  - Optimizing some CLI functions for Render/web-friendly application
  - README/documentation updates
