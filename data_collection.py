"""
Data collection and cleaning pipeline for Burgh Date Planner.

Refactored from teammate notebook logic and wired to project config paths.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup

from config import (
    DATA_SOURCES,
    SCRAPE_REQUEST_TIMEOUT_SECONDS,
    SCRAPED_EVENT_COLUMNS,
    SCRAPED_OUTPUT_FILES,
)
from utils import ensure_project_directories

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

MAX_PAGES = 3
LISTING_SLEEP_SECONDS = 1.5
DETAIL_SLEEP_SECONDS = 1.2

PGH_EVENTS_SOURCE_KEY = "pgh_events"
EVENTBRITE_SOURCE_KEY = "eventbrite"

OUTPUT_FILE = Path(SCRAPED_OUTPUT_FILES["final_csv"])

MANUAL_LOCATION_FIXES = {
    "Eddy TheatreWoodland": "Eddy Theatre",
    "Wyndham Grand": "Wyndham Grand Pittsburgh Downtown",
    "The Circuit Center Hot Metal": "The Circuit Center",
    "1139 Penn": "1139 Penn Ave",
}


def clean(text: str | None) -> str:
    return " ".join(text.split()) if text else "N/A"


def get_text(element: Any) -> str:
    return clean(element.get_text()) if element else "N/A"


def _eventbrite_listing_page_url(page_num: int) -> str:
    base_url = str(DATA_SOURCES[EVENTBRITE_SOURCE_KEY]["url"])
    if page_num == 1:
        return base_url
    return f"{base_url}?page={page_num}"


def scrape_pgh_events(
    max_pages: int = MAX_PAGES,
    request_timeout: int = SCRAPE_REQUEST_TIMEOUT_SECONDS,
) -> list[dict[str, str]]:
    pgh_events: list[dict[str, str]] = []

    for page_num in range(1, max_pages + 1):
        url = "https://pgh.events/" if page_num == 1 else f"https://pgh.events/?page={page_num}"
        print(f"[pgh.events] Fetching page {page_num}: {url}")
        try:
            response = requests.get(url, headers=HEADERS, timeout=request_timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"  ✗ {exc}")
            break

        soup = BeautifulSoup(response.text, "html.parser")
        day_blocks = soup.select("[class*='day-module--day']")
        if not day_blocks:
            print("  ✗ No day blocks found.")
            break
        print(f"  ✓ {len(day_blocks)} day block(s) found.")

        for day in day_blocks:
            day_time_el = day.select_one("time")
            day_date = day_time_el.get("datetime", "N/A")[:10] if day_time_el else "N/A"

            for card in day.select("[class*='event-module--event']"):
                name_el = card.select_one("[class*='event-module--mainLink']")
                event_name = get_text(name_el)

                link_el = name_el if (name_el and name_el.name == "a") else card.select_one("a[href]")
                source_url = link_el["href"] if link_el else "N/A"
                if source_url != "N/A" and source_url.startswith("/"):
                    source_url = "https://pgh.events" + source_url

                location = "N/A"
                for paragraph in card.select("p"):
                    if not paragraph.get("class"):
                        text = clean(paragraph.get_text())
                        if text and text != "N/A":
                            location = text
                            break

                card_time_el = card.select_one("time")
                event_date = day_date
                event_time = "N/A"
                if card_time_el:
                    raw_dt = card_time_el.get("datetime", "")
                    if raw_dt and "T" in raw_dt:
                        try:
                            dt = datetime.strptime(
                                re.sub(r"[+-]\d{4}$", "", raw_dt),
                                "%Y-%m-%dT%H:%M:%S",
                            )
                            event_date = dt.strftime("%Y-%m-%d")
                            event_time = dt.strftime("%I:%M %p")
                        except ValueError:
                            event_date = raw_dt[:10]

                price_el = card.select_one("[class*='price']") or card.select_one("[class*='cost']")
                price = get_text(price_el)
                if price == "N/A":
                    matched = re.search(r"(Free|\$[\d,.]+)", card.get_text(), re.IGNORECASE)
                    price = matched.group(0) if matched else "N/A"

                pgh_events.append(
                    {
                        "event_name": event_name,
                        "date": event_date,
                        "time": event_time,
                        "location": location,
                        "price": price,
                        "source": "pgh.events",
                        "url": source_url,
                    }
                )

        print(f"  → {len(pgh_events)} events so far.")
        time.sleep(LISTING_SLEEP_SECONDS)

    print(f"\n[pgh.events] Total: {len(pgh_events)} events\n")
    return pgh_events


def parse_eventbrite_datetime(soup: BeautifulSoup, raw_html: str) -> tuple[str, str]:
    # Strategy 1: <time datetime="...">
    time_el = soup.select_one("time[datetime]")
    if time_el:
        try:
            dt = datetime.fromisoformat(time_el.get("datetime", "").replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d"), dt.strftime("%I:%M %p")
        except ValueError:
            pass

    # Strategy 2: JSON-LD structured data.
    for script in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(script.string or "")
            start = data.get("startDate", "")
            if start:
                dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                return dt.strftime("%Y-%m-%d"), dt.strftime("%I:%M %p")
        except Exception:
            continue

    # Strategy 3: regex on raw HTML.
    iso = re.search(r'"startDate"\s*:\s*"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', raw_html)
    if iso:
        try:
            dt = datetime.fromisoformat(iso.group(1))
            return dt.strftime("%Y-%m-%d"), dt.strftime("%I:%M %p")
        except Exception:
            pass

    # Strategy 4: human-readable text.
    date_pat = re.compile(
        r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2})(?:,?\s*(\d{4}))?",
        re.IGNORECASE,
    )
    time_pat = re.compile(r"\b(\d{1,2}:\d{2}\s*(?:AM|PM))\b", re.IGNORECASE)
    text = soup.get_text(" ")
    event_date = "N/A"
    event_time = "N/A"
    date_match = date_pat.search(text)
    time_match = time_pat.search(text)

    if date_match:
        try:
            dt = datetime.strptime(
                f"{date_match.group(1)} {date_match.group(2)} {date_match.group(3) or '2026'}",
                "%B %d %Y",
            )
            event_date = dt.strftime("%Y-%m-%d")
        except Exception:
            event_date = f"{date_match.group(1)} {date_match.group(2)}, 2026"
    if time_match:
        event_time = time_match.group(1).upper().replace(" ", "")
    return event_date, event_time


def parse_eventbrite_location(soup: BeautifulSoup) -> str:
    for selector in [
        "[data-spec='venue-name']",
        "[class*='venue-name']",
        "[class*='location-info__address']",
        "address",
    ]:
        element = soup.select_one(selector)
        if element:
            text = clean(element.get_text())
            if text and len(text) < 100:
                return text
    candidates = [
        clean(element.get_text())
        for element in soup.find_all(["p", "span", "div", "address"])
        if "Pittsburgh" in clean(element.get_text()) and 5 < len(clean(element.get_text())) < 80
    ]
    return min(candidates, key=len) if candidates else "N/A"


def scrape_eventbrite(
    max_pages: int = MAX_PAGES,
    request_timeout: int = SCRAPE_REQUEST_TIMEOUT_SECONDS,
) -> list[dict[str, str]]:
    print("[Eventbrite] Step 1: Collecting event URLs...")
    eb_urls: list[str] = []

    for page_num in range(1, max_pages + 1):
        url = _eventbrite_listing_page_url(page_num)
        print(f"  Fetching listing page {page_num}")
        try:
            response = requests.get(url, headers=HEADERS, timeout=request_timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"  ✗ {exc}")
            break

        soup = BeautifulSoup(response.text, "html.parser")
        found: list[str] = []
        for anchor in soup.select("a[href*='/e/']"):
            href = str(anchor.get("href", "")).split("?")[0]
            if href and href not in eb_urls and href not in found:
                found.append(href)
        eb_urls.extend(found)
        print(f"  ✓ {len(found)} URLs found on page {page_num}.")
        time.sleep(LISTING_SLEEP_SECONDS)

    print(f"\n[Eventbrite] {len(eb_urls)} URLs. Fetching detail pages...\n")
    eb_events: list[dict[str, str]] = []
    for index, event_url in enumerate(eb_urls, start=1):
        print(f"  [{index}/{len(eb_urls)}] {event_url}")
        try:
            response = requests.get(event_url, headers=HEADERS, timeout=request_timeout)
            response.raise_for_status()
        except Exception:
            time.sleep(1.0)
            continue

        detail = BeautifulSoup(response.text, "html.parser")
        name_el = detail.select_one("h1") or detail.select_one("[class*='event-title']")
        event_name = get_text(name_el)
        event_date, event_time = parse_eventbrite_datetime(detail, response.text)
        location = parse_eventbrite_location(detail)
        price_el = detail.select_one("[class*='ticket-price']") or detail.select_one(
            "[class*='conversion-bar']"
        )
        price = get_text(price_el)
        if price == "N/A":
            matched = re.search(r"(Free|\$[\d,.]+)", response.text)
            price = matched.group(0).capitalize() if matched else "N/A"

        eb_events.append(
            {
                "event_name": event_name,
                "date": event_date,
                "time": event_time,
                "location": location,
                "price": price,
                "source": "Eventbrite",
                "url": event_url,
            }
        )
        time.sleep(DETAIL_SLEEP_SECONDS)

    print(f"\n[Eventbrite] Total: {len(eb_events)} events\n")
    return eb_events


def clean_location(location: Any) -> Any:
    if not isinstance(location, str) or location == "N/A":
        return location
    if not re.match(r"^\d", location):
        location = re.sub(r"([a-zA-Z])(\d)", r"\1", location).strip()
    location = re.split(r"\s+\d{1,5}\s+", location)[0].strip()
    location = re.sub(r",?\s*Pittsburgh.*$", "", location, flags=re.IGNORECASE).strip()
    location = re.sub(
        r"\s+(Road|Street|Ave|Avenue|Blvd|Boulevard|Drive|Lane|Way)$",
        "",
        location,
        flags=re.IGNORECASE,
    ).strip()
    return location.strip(" ,") if location else "N/A"


def build_dataframe(all_events: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(all_events, columns=SCRAPED_EVENT_COLUMNS)
    if df.empty:
        return df
    df = df[df["event_name"].str.strip().str.len() > 0]
    df = df[df["event_name"] != "N/A"]
    df.drop_duplicates(subset=["event_name", "date"], inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = df.fillna("N/A").copy()
    if cleaned.empty:
        return cleaned
    cleaned["location"] = cleaned["location"].apply(clean_location)
    cleaned["location"] = cleaned["location"].replace(MANUAL_LOCATION_FIXES)
    cleaned["price"] = cleaned["price"].apply(
        lambda price: price.rstrip(".") if isinstance(price, str) else price
    )
    return cleaned


def save_csv(df: pd.DataFrame, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"\n{'=' * 50}")
    print(f"✅  {len(df)} events saved to {path}")
    print(f"{'=' * 50}")
    if not df.empty:
        print(df[["event_name", "date", "time", "location", "price", "source"]].to_string(index=False))
    return path


def load_csv(path: Path | str) -> pd.DataFrame:
    df = pd.read_csv(Path(path))
    return df.fillna("N/A")


def _save_collection_output(cleaned_df: pd.DataFrame, final_output_file: Path) -> None:
    save_csv(cleaned_df, final_output_file)


def _empty_raw_sources() -> dict[str, list[dict[str, Any]]]:
    return {source_key: [] for source_key in DATA_SOURCES}


def collect_raw_sources(
    max_pages: int = MAX_PAGES,
    request_timeout: int = SCRAPE_REQUEST_TIMEOUT_SECONDS,
    save_outputs: bool = True,
) -> tuple[dict[str, list[dict[str, Any]]], pd.DataFrame]:
    """
    Collect fresh source data and optionally persist the final CSV.
    """
    ensure_project_directories()

    pgh_events = scrape_pgh_events(max_pages=max_pages, request_timeout=request_timeout)
    eventbrite_events = scrape_eventbrite(max_pages=max_pages, request_timeout=request_timeout)
    all_events = pgh_events + eventbrite_events

    raw_sources = _empty_raw_sources()
    raw_sources[PGH_EVENTS_SOURCE_KEY] = pgh_events
    raw_sources[EVENTBRITE_SOURCE_KEY] = eventbrite_events

    if not all_events:
        return raw_sources, pd.DataFrame(columns=SCRAPED_EVENT_COLUMNS)

    cleaned_df = clean_dataframe(build_dataframe(all_events))
    if save_outputs:
        _save_collection_output(cleaned_df, OUTPUT_FILE)
    return raw_sources, cleaned_df


def prompt_user(output_file: Path | str = OUTPUT_FILE) -> bool:
    output_file = Path(output_file)
    cached_exists = output_file.exists()

    print("=" * 60)
    print("  Pittsburgh Date Night App — Lime Team")
    print("=" * 60)
    if cached_exists:
        print(f"\n  Cached dataset found: {output_file}\n")
        print("  [1] Use cached data  (instant)")
        print("  [2] Download fresh data  ( ~3-5 minutes)\n")
        while True:
            choice = input("  Enter 1 or 2: ").strip()
            if choice == "1":
                return False
            if choice == "2":
                confirm = input("  Are you sure? (y/n): ").strip().lower()
                return confirm == "y"
            print("  Please enter 1 or 2.")

    print("\n  No cached data found. Fresh download required (~3-5 mins).")
    input("  Press Enter to start...")
    return True


def main() -> None:
    ensure_project_directories()
    use_fresh = prompt_user(OUTPUT_FILE)

    if use_fresh:
        print("\n[Starting fresh scrape...]\n")
        _raw_sources, cleaned_df = collect_raw_sources(save_outputs=False)

        if cleaned_df.empty:
            print("No events collected.")
            return

        _save_collection_output(cleaned_df, OUTPUT_FILE)
    else:
        print(f"\n[Loading cached data...]\n")
        cached_df = load_csv(OUTPUT_FILE)
        cleaned_df = clean_dataframe(cached_df)
        save_csv(cleaned_df, OUTPUT_FILE)


if __name__ == "__main__":
    main()
