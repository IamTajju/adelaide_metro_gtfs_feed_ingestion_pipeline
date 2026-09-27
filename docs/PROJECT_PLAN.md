# Project Plan — Adelaide Metro Data Ingestion (COMP9742 Artefact 1)

**A1 (due Thu 8 Oct 2026, 16:30):** deliver a working, automated ingestion pipeline.
After A1 the collector keeps running on the chosen routes and stops until A2, building
the dataset for delay prediction and weather patterns.

**Rule:** path of least resistance, always.

**Data sources (all public, no primary research)**

| Source | Used for |
|---|---|
| [Adelaide Metro Validations](https://data.sa.gov.au/data/dataset/adelaide-metrocard-validations) (tap-ons per day × route × stop) | Demand: choosing routes and stops |
| [Adelaide Metro GTFS](https://gtfs.adelaidemetro.com.au/#/gtfs): static + real-time vehicle positions | Stop locations, scheduled times, live bus positions |
| [Transitland](https://www.transit.land/feeds/f-r1f-adelaidemetrocomau): archived timetable versions | How much routes change |
| [Open-Meteo](https://open-meteo.com/) | Hourly weather |

---

## Stage 1 — Route centric

- **How often route timetables change:** download one archived timetable from ~6 months
  ago from Transitland (free API key) and compare it with the current one. For each route,
  compute change = |weekday trips now − weekday trips then| ÷ weekday trips then.
  *If Transitland is blocked or slow, drop this criterion and say so in the report.*
- **Top k routes:**
  1. Candidates: the top 15 bus routes by boardings at CBD stops (latest validations quarter).
  2. Rank the candidates on three criteria: demand (CBD boardings), frequency
     (weekday trips), stability (lowest change).
  3. Sum the ranks and keep the lowest `k` (k = 5).
- **Visualisation:**
  - bar chart of the candidates by boardings (chosen k highlighted)
  - map of the chosen routes
  - rank heatmap: candidates × the three criteria, coloured by rank, sorted by total (shows *why* the top k won)

## Stage 2 — Top m stops in the CBD

- **N/S/E/W scoping:** CBD = the box inside the four terraces; the quadrant is decided
  relative to Victoria Square. The final stops must cover all four quadrants.
- **Top n stops per route:** the route's CBD stops ranked by boardings on that route
  (n = 3). If a quadrant is missing, swap the lowest pick for the best stop in that quadrant.
  m = the set of all picks.
- **Visualisation:** a CBD map of the chosen stops, coloured by quadrant.

## Stage 3 — Real-time positions of those buses approaching those stops

- **Frequency and periods:** poll vehicle positions at the feed's refresh rate (check it
  once; ~30 s). Collect daily from the first to the last scheduled bus at the chosen stops.
- **Filter:** keep a position only if it is on a chosen route **and** within 500 m of a chosen stop.
- **Delay inputs:** store the scheduled arrival times (from the timetable) for the chosen
  trips × stops. After collection, the observed arrival = the ping closest to the stop.
  Store both times; the delay definition is decided in A2. Reload the scheduled times
  when the timetable version changes (checked daily).
- **Rejection layer (before storing):** required fields present, position inside SA,
  timestamp fresh, trip exists in the timetable. Bad rows go to `quarantine` with the reason.
- **Anomaly layer (after collection, daily):** flag vehicle jumps, polling gaps,
  scheduled trips never seen, and arrivals more than 1 h off schedule. Flags only; nothing is deleted.

## Stage 4 — Weather for the chosen times

- **Source:** Open-Meteo (free, no key, hourly, past dates). Fetched once a day for yesterday.
- **Stored:** temperature, precipitation, wind speed, weather code, for the collection hours only.

---

## Architecture

```
validations + static GTFS (+ Transitland) ─► select_routes.py ─► select_stops.py ─► routes.csv, stops.csv
                                                                                         │
live vehicle positions ─► collect.py ─► validate.py ─► SQLite (data/gtfs.db) ◄──────────┘
                                             └─► quarantine
daily (cron): timetable.py (version check) · weather.py · arrivals.py · anomalies.py
```

Python + SQLite + pandas + matplotlib, on one machine.

## Timeline

| Dates | Work | Tickets |
|---|---|---|
| 26–27 Sep | Setup + Stage 1 | T01–T04 |
| 28 Sep | Stage 2 | T05 |
| 29 Sep – 2 Oct | Stage 3 | T06–T10 |
| 3 Oct | Stage 4 | T11 |
| 4–7 Oct | CLI, demo run, report, video, package | T12–T17 |
| **8 Oct 16:30** | **Submit A1**. The collector keeps running until A2. | |

## Limitations (for the report)

- Validations are a quarter behind, grouped into ranges, and count tap-ons only.
- The stability check compares only two timetable versions.
