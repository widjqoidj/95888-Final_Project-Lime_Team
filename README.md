# Burgh Event Planner

Team Name: Lime Team  
Group Members (Andrew IDs):
- Disheng Lu (dishengl)
- (Name) (andrewid)
- (Name) (andrewid)

## Product Vision
Make event discovery in Pittsburgh faster by surfacing relevant suggestions based on budget and time of day.

## Overview
`Burgh Date Planner` collects Pittsburgh event listings from multiple web sources, saves a cleaned CSV output, and generates ranked event suggestions in a CLI.

## Current Workflow
1. `data_collection.py` scrapes and cleans events from configured sources.
2. Cleaned data is saved to `data/pittsburgh_events.csv`.
3. `main.py` loads that CSV and validates a strict input schema.
4. `recommend.py` filters and ranks events by budget, preferred period (`morning`, `afternoon`, `evening`), and optional event date.

## Data Sources
- Eventbrite Pittsburgh (`https://www.eventbrite.com/d/pa--pittsburgh/all-events/`)
- PGH.Events (`https://pgh.events/`)

Source configuration lives in `config.py`.

## CSV Schema
`data/pittsburgh_events.csv` currently contains:
- `event_name`
- `date`
- `time`
- `location`
- `price`
- `source`
- `url`
- `max_price` (derived numeric upper-bound price when available)

During loading, `event_name` is normalized to `name` for recommendation.

In schema validation, `main.py` strictly requires the first seven columns above and allows extra columns (such as `max_price`).

## Tech Stack
- Python 3.10+
- `requests`, `beautifulsoup4`, `pandas`

## Installation
1. Clone/download this project folder.
2. Create and activate a virtual environment.
3. Install dependencies manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run
1. Collect or refresh event data:

```bash
python3 data_collection.py
```

2. Run the recommendation CLI:

```bash
python3 main.py
```

The CLI prompts for:
- max budget (USD)
- optional event date filter (`YYYY-MM-DD`)
- preferred time of day (`morning`, `afternoon`, `evening`, `any`)
- number of suggestions to generate

## Project Structure
```
.
├── main.py
├── config.py
├── data_collection.py
├── recommend.py
├── utils.py
├── requirements.txt
├── .env.example
├── data/
│   └── pittsburgh_events.csv
```

## Recommendation Logic
`recommend.py` performs:
1. Input validation for required recommendation fields.
2. Price parsing from text (for example, `Free`, `$15`, `$10-$20`).
3. Datetime synthesis from `date` + `time`.
4. Filtering by budget, preferred period, and optional event date.
5. Scoring with weighted budget/time scores and ranking.

## Notes
- `main.py` uses a strict schema check; missing required CSV columns will raise an error.
- If no suggestions match, try a different date, period, or a higher budget.

## GenAI Use
- Model: ChatGPT-5.3-Codex
- Use case: 
    - Help with integration of data collection script to overall project codebase
    - Configration and utility file setup
    - Improvement and validation checks of recommendation logic
    - Writing README.md


## Rubric Alignment Checklist
- 2+ online data sources: yes (2 configured)
- at least 1 scraped source: yes (2 configured)
- full Python pipeline (collect -> clean -> recommend -> output): yes
- user interaction: yes (menu-based CLI)
- one runnable main file: yes (`main.py`)
