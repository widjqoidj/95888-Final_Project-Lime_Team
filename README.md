# 95888 Final Project — Lime Team

## Team Name
**Lime Team**

## Andrew IDs
- khrisopo@andrew.cmu.edu
- dishengl@andrew.cmu.edu
- knorris2@andrew.cmu.edu

---

## Project Description
This project scrapes Pittsburgh event listings from two websites — **pgh.events** and **Eventbrite** — cleans the data, and outputs a structured CSV file (`pittsburgh_events.csv`) for use in a Pittsburgh Date Night recommendation app.

---

## How to Run

### 1. Install dependencies
```bash
pip install requests beautifulsoup4 pandas
```

### 2. Open the notebook
Open `Data_Scrape_Clean_Output_Final_project_Lime_Team.ipynb` in Jupyter Notebook 

### 3. Run the single cell
 Run it and you will be prompted:

```
============================================================
  Pittsburgh Date Night App — Lime Team
============================================================

  Cached dataset found: .../pittsburgh_events.csv

  [1] Use cached data  (instant)
  [2] Download fresh data  (⚠️  ~3-5 minutes)

  Enter 1 or 2:
```

- **Enter `1`** — loads the included `pittsburgh_events.csv` instantly
- **Enter `2`** — scrapes live data from both websites (~3-5 minutes)

---

## Output
A file called `pittsburgh_events.csv` is saved in the same folder as the notebook, with these columns:

| Column | Description |

| `event_name` | Name of the event |
| `date` | Date in YYYY-MM-DD format |
| `time` | Start time in HH:MM AM/PM format |
| `location` | Venue name |
| `price` | Ticket price or "Free" or "N/A" |
| `source` | `pgh.events` or `Eventbrite` |
| `url` | Direct link to the event page |

---

## Notes
- **pgh.events prices** are mostly N/A — the site does not publish ticket prices on its listing pages. Follow the URL for pricing details.
- **Eventbrite** uses a two-step scrape: listing pages are used to collect event URLs, then each event's detail page is fetched individually for full data. This is necessary because Eventbrite's listing pages are JavaScript-rendered.
- The scraper uses delays (1.2–1.5 seconds) between requests to avoid overloading servers.
- Fresh scraped data may differ from the cached CSV since events are added and removed daily.
