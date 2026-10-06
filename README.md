# Adelaide Metro Data Ingestion Pipeline

COMP9742 Artefact 1: the data ingestion module for a bus delay prediction and
weather patterns engine.

1. Choose the top k bus routes from public demand data (Stage 1)
2. Choose the top n CBD stops per route, covering N/S/E/W (Stage 2)
3. Collect live positions of those buses near those stops, reject bad rows, store
   scheduled times, flag anomalies (Stage 3)
4. Add hourly weather (Stage 4)

Plan: [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) · Tickets: [docs/TICKETS.md](docs/TICKETS.md)

## Skeleton

Each stage is a package with a `main.py` driver (`python -m <package>`) and its helpers.

Stage 1 commands:

- `make candidates`: route candidates, the top 15 routes by CBD boardings → `data/selection/route_candidates_<timestamp>.csv` + map
- `make selection`: final top k routes from the latest route candidates. Score = 0.6 × boardings rank + 0.4 × weekday-trips
  rank (lower is better). The best route heading N, E, S and W from Victoria Square is taken first, then the
  rest by score → `data/selection/top_k_routes_<timestamp>.csv` + map

```
data_ingestion.py            CLI front door (calls each stage's main)
shared/
  config.py                  settings: URLs, paths, CBD box, k, n, radius, poll interval
  store.py                   SQLite tables
  timetable.py               static GTFS download + version check, bus routes, CBD stops
select_routes/               Stage 1
  main.py                    demand → route candidates (+ map)
  selection.py               weighted rank + N/E/S/W coverage → top k (+ map)
  validations.py             Metrocard validations download
  plots.py                   bar chart, route map, rank heatmap
select_stops/                Stage 2
  main.py                    top n CBD stops per route, N/S/E/W
  plots.py                   CBD stop map
gtfs_position_collection/    Stage 3
  main.py                    polling loop with route + radius filter
  scheduled_times.py         scheduled arrivals for chosen trips × stops
  validate.py                rejection layer
  arrivals.py                observed vs scheduled arrival
  anomalies.py               post-collection flags
weather_collection/          Stage 4
  main.py                    Open-Meteo hourly
tests/                       tests for the rejection layer
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
