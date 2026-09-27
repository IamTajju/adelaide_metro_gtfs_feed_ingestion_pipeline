# Tickets

Work in order. Each one is small. Strategy: `PROJECT_PLAN.md`.

## Setup

### [ ] T01 — Skeleton, config, database
File headers (name, FAN, date); venv; `config.py` (URLs, CBD box, Victoria Square, k = 5,
n = 3, radius = 500 m, poll = 30 s); `store.py` creates the tables.
**Done when:** `python data_ingestion.py init` creates `data/gtfs.db`.

## Stage 1 — Routes

### [ ] T02 — Demand candidates
Download the latest validations quarter. Keep buses; merge variants (`300H` → `300`);
sum `BAND_BOARDINGS_FLOOR` at CBD stops per route. Keep the top 15 as candidates.
**Done when:** `data/selection/candidates.csv` lists 15 routes with boardings.

### [ ] T03 — Timetable change
Get a free Transitland key; download the Adelaide Metro version from ~6 months ago.
Change per candidate = |weekday trips now − then| ÷ then.
If blocked, skip it and note it in the README.
**Done when:** a `change` column is added to the candidates (or the criterion is dropped).

### [ ] T04 — Rank and pick top k
Rank on demand, weekday trips and change; sum the ranks; keep the lowest 5 → `routes.csv`.
Plot the bar chart, the route map and the rank heatmap (candidates × criteria).
**Done when:** `routes.csv` and 3 PNGs exist.

## Stage 2 — Stops

### [ ] T05 — Top n stops per route
CBD stops per chosen route, tagged N/S/E/W, ranked by boardings on that route; top 3;
swap to cover all quadrants → `stops.csv`. Plot the CBD map.
**Done when:** `stops.csv` covers all four quadrants, plus 1 PNG.

## Stage 3 — Real-time pipeline

### [ ] T06 — Scheduled times
Download the static timetable; load the scheduled arrivals for the chosen trips × stops into
`scheduled_stop_times`. Check `version.txt` daily and reload if it changed.
**Done when:** the table is filled for the current version.

### [ ] T07 — Rejection layer + tests
`validate.py`: required fields, position inside SA, timestamp fresh, trip exists.
Bad rows → `quarantine` with the reason. One test per rule.
**Done when:** `pytest` passes.

### [ ] T08 — Collector
Every 30 s between the first and last scheduled bus: fetch → skip if unchanged → keep chosen
routes within 500 m of a chosen stop → validate → store. Log each fetch; never crash.
**Done when:** a 1-hour run stores only the filtered pings.

### [ ] T09 — Observed arrivals
Per trip × stop × date: the closest ping = observed arrival, stored next to the scheduled time.
**Done when:** the `arrivals` table is filled from the 1-hour run.

### [ ] T10 — Anomaly flags
Daily: vehicle jumps, polling gaps, trips never seen, arrivals more than 1 h off schedule → `anomalies`.
**Done when:** it prints counts per rule.

## Stage 4 — Weather

### [ ] T11 — Weather
Open-Meteo hourly temperature, precipitation, wind and weather code for yesterday's collection hours → `weather_hourly`.
**Done when:** the rows for yesterday exist.

## Run and submit

### [ ] T12 — CLI
`data_ingestion.py`: `init, select, collect, daily, status, export`. Cron runs `daily`.
**Done when:** a fresh clone runs end to end.

### [ ] T13 — Demo run + EDA figures for the report
### [ ] T14 — Tidy: docstrings, `pip freeze`, README limitations
### [ ] T15 — Report (~1,500 words) + self-assessment + AI declaration
### [ ] T16 — Video (3–5 min)
### [ ] T17 — Zip `A1_<FAN>/` (no data or venv) and submit by 8 Oct 16:30
