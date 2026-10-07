# Adelaide Metro Data Ingestion Pipeline

COMP9742 Artefact 1: the data ingestion module for a bus delay prediction and
weather patterns engine.

1. Choose the top k bus routes from public demand data (Stage 1)
2. Choose the top n CBD stops per route, covering N/S/E/W (Stage 2)
3. Collect live positions of those buses near those stops, reject bad rows, store
   scheduled times, flag anomalies (Stage 3)
4. Add hourly weather (Stage 4)

Plan: [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) · Tickets: [docs/TICKETS.md](docs/TICKETS.md)

## Commands

`make` lists the commands. `make selection` runs the four Stage 1 and 2 steps below in order.

Stage 1 commands:

- `make route_candidates`: route candidates, the top 15 routes by CBD boardings → `data/selection/route_candidates_<timestamp>.csv` + route map + bar charts
- `make route_selection`: final top k routes from the latest route candidates. Score = 0.6 × boardings rank + 0.4 × weekday-trips
  rank (lower is better). The best route heading N, E, S and W from Victoria Square is taken first, then the
  rest by score → `data/selection/top_k_routes_<timestamp>.csv` + map

Stage 2 commands:

- `make stop_candidates`: every CBD stop served by the latest top k routes, with its boardings on that route → `data/selection/stop_candidates_<timestamp>.csv`
- `make stop_selection`: top 3 stops per route by boardings, tagged N/E/S/W from Victoria Square; a missing quadrant's best
  stop replaces its route's lowest pick → `data/selection/top_m_stops_<timestamp>.csv` + CBD map

Database and Stage 3 commands:

- `venv/bin/python -m data_collection_setup`: creates `data/gtfs.db` with the four tables below. Re-runs keep existing
  rows; `--reset` deletes the database first (wipes every collected position).
- `venv/bin/python -m gtfs_position_collection.arrivals`: fills `arrivals` from the stored positions (closest ping to
  each chosen stop per trip and day, next to its scheduled time). Safe to re-run.

## Database

One SQLite file, `data/gtfs.db` (`config.DB_PATH`), defined in `data_collection_setup/main.py`:

| Table | Holds | Key |
|---|---|---|
| `routes` | the top k routes (boardings, weekday trips, ranks, score, direction) | `route` |
| `stops` | the top m stops per route (boardings, quadrant, rank) | `(route, stop_id)` → `routes` |
| `positions` | live pings of chosen routes near chosen stops | `UNIQUE (vehicle_id, timestamp)`; `route` (base code) → `routes` |
| `arrivals` | observed vs scheduled arrival per trip, stop and service date | `(trip_id, stop_id, service_date)` |

`positions.trip_route_id` keeps the feed's raw id (e.g. `G10A`); `positions.route` is its base code (`G10`). With
`PRAGMA foreign_keys = ON`, replace a selection in this order: delete `stops`, then `routes`; insert `routes`, then `stops`.

## Skeleton

Each stage is a package with a `main.py` driver (`python -m <package>`) and its helpers.

```
data_ingestion.py            CLI front door (calls each stage's main)
shared/
  config.py                  settings: URLs, paths (incl. DB_PATH), CBD box, k, n, poll interval
  timetable.py               static GTFS download + version check, read_gtfs, bus routes, CBD stops,
                             weekday trip counts, route shapes
data_collection_setup/       Database
  main.py                    creates data/gtfs.db: routes, stops, positions, arrivals (--reset to wipe)
select_routes/               Stage 1
  main.py                    driver: route candidates CSV + map + bar charts
  candidates.py              rank routes by CBD boardings
  selection.py               weighted rank + N/E/S/W coverage → top k (+ map)
  validations.py             Metrocard validations download
  plots.py                   route map, boardings + weekday trips bar charts, rank heatmap (TODO)
select_stops/                Stage 2
  main.py                    driver: stop candidates CSV
  candidates.py              CBD stops served by the top k routes (timetable chain) + boardings
  selection.py               top n stops per route + N/E/S/W quadrant swap → top m stops
  plots.py                   CBD stop map
gtfs_position_collection/    Stage 3
  main.py                    polling loop: fetch → filter → validate → store (TODO, T08)
  filters.py                 keep pings of chosen routes within 500 m of a chosen stop
  scheduled_times.py         scheduled arrivals for chosen trips × stops
  validate.py                rejection layer
  arrivals.py                observed (closest ping) vs scheduled arrival → arrivals table
  anomalies.py               post-collection flags
weather_collection/          Stage 4
  main.py                    Open-Meteo hourly
tests/                       filter and arrivals tests (rejection layer tests: TODO, T07)
```

## Setup and run

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python data_ingestion.py init      # create the database
venv/bin/python data_ingestion.py select    # choose routes and stops
venv/bin/python data_ingestion.py collect   # poll live positions (leave running)
venv/bin/python data_ingestion.py daily     # version check, weather, arrivals, anomalies
venv/bin/python data_ingestion.py status    # what's been collected
venv/bin/python data_ingestion.py export    # tables → CSV
```

## Known limitations

- Validations are a quarter behind, grouped into ranges, and count tap-ons only.
- Delay is not defined yet (decided in A2); scheduled and observed times are stored.
- An observed arrival is the closest stored ping within 500 m, not the moment the bus reached the stop; at the
  poll interval it can be a minute or more off. `arrivals.distance_m` records how close that ping was.
