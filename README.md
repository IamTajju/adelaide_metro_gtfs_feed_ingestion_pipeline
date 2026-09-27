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

```
data_ingestion.py   CLI front door
config.py           settings
store.py            SQLite tables
select_routes.py    Stage 1: demand → candidates → rank → top k
select_stops.py     Stage 2: top n CBD stops per route, N/S/E/W
timetable.py        Stage 3: static timetable, version check, scheduled times
collect.py          Stage 3: polling loop with route + radius filter
validate.py         Stage 3: rejection layer
arrivals.py         Stage 3: observed vs scheduled arrival
anomalies.py        Stage 3: post-collection flags
weather.py          Stage 4: Open-Meteo hourly
plots.py            charts and maps
tests/              tests for validate.py
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
