"""
Central project configuration and filesystem paths.
Single-output CSV setup.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"

DEFAULT_CITY = "Pittsburgh, PA"
DEFAULT_MAX_RESULTS = 3
SCRAPE_REQUEST_TIMEOUT_SECONDS = 15

SCRAPED_EVENT_COLUMNS = [
    "event_name",
    "date",
    "time",
    "location",
    "price",
    "source",
    "url",
]

# Standardized schema for scraped event outputs.
STANDARD_COLUMNS = SCRAPED_EVENT_COLUMNS

# Final output CSV file location.
SCRAPED_OUTPUT_FILES = {
    "final_csv": DATA_DIR / "pittsburgh_events.csv",
}

# Recommendation module compatibility.
RECOMMENDATION_SAMPLE_FILE = SCRAPED_OUTPUT_FILES["final_csv"]
LATEST_OPTIONS_FILE = SCRAPED_OUTPUT_FILES["final_csv"]

DATA_SOURCES = {
    "eventbrite": {
        "type": "scrape",
        "url": "https://www.eventbrite.com/d/pa--pittsburgh/all-events/",
    },
    "pgh_events": {
        "type": "scrape",
        "url": "https://pgh.events/",
    },
}
