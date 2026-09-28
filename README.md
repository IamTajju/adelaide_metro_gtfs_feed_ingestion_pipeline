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

```
data_ingestion.py            CLI front door (calls each stage's main)
shared/
  config.py                  settings: URLs, paths, CBD box, k, n, radius, poll interval
  store.py                   SQLite tables
  timetable.py               static GTFS download + version check, bus routes, CBD stops
data_collection_setup/        whole feed, unfiltered
  main.py                    static GTFS + validations quarter → SQLite
get_gtfs_positions/           one snapshot of live positions
  main.py                    vehicle_positions feed → data/gtfs_positions.csv
gtfs_position_collection/     Stage 3
  main.py                    polling loop → gtfs_positions table (every 15 s)
select_routes/               Stage 1
  main.py                    demand → candidates → rank → top k
  validations.py             Metrocard validations download
  plots.py                   bar chart, route map, rank heatmap
select_stops/                Stage 2
  main.py                    top n CBD stops per route, N/S/E/W
  plots.py                   CBD stop map
weather_collection/          Stage 4
  main.py                    Open-Meteo hourly
tests/                       tests for the rejection layer
```

## Setup and run

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python -m data_collection_setup        # load the full GTFS + validations into data/gtfs.db
venv/bin/python -m get_gtfs_positions           # save one live snapshot to data/gtfs_positions.csv
venv/bin/python -m gtfs_position_collection     # poll live positions into gtfs_positions (leave running)
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
