# Adelaide Metro Data Ingestion Pipeline

A small pipeline that pulls live bus/train data from Adelaide Metro, checks it,
and stores it so we can query it later.

Data source: https://gtfs.adelaidemetro.com.au/#/gtfs

---

## The four decisions

### 1. Store in SQLite, not CSV

We write to a **SQLite database** (`data/gtfs.db`). CSV is only used for
**exports** at the end.

Why:

- The live feeds repeat. Vehicle positions refresh every 15 seconds. That is a maximum of
  about **3.8 million rows a day**.
- The same bus shows up again and again. A database can say "I already have
  this row, skip it". A CSV cannot.
- We need to ask questions like "how late was route 300 last Tuesday". That is
  one line of SQL, but a big script over CSV files.
- SQLite is one file. No server, no install, no password. It is already inside
  Python.

CSV is still good for handing data to someone else, so `export.py` turns any
query into a CSV when we need one.

### 2. Real-time processing = polling on a timer

We do **not** need Kafka or streaming tools. The feeds are plain files that get
replaced every few seconds. So we just ask for them on a timer.

| Feed | How often it changes | How often we ask |
|---|---|---|
| Vehicle positions | 15 seconds | every 15 seconds |
| Trip updates | 60 seconds | every 60 seconds |
| Service alerts | 5 minutes | every 5 minutes |
| Static timetable | rarely | once a day |

Each feed carries its own clock (`feed_timestamp`). If the clock has not moved
since last time, the data is the same as before, so we throw it away and do not
write it. This saves a lot of space.

### 3. Bad data detection = three layers

Real feeds break. GPS jumps into the ocean, fields go missing, a whole feed
comes back empty. We check in three places:

**Layer 1 — row checks.** Is this one row sane on its own?
- Required fields are there (trip id, vehicle id).
- Latitude and longitude are actually inside South Australia.
- Speed is not impossible (no 300 km/h buses).
- Timestamp is not in the future and not ancient.

**Layer 2 — batch checks.** Does this whole fetch look right?
- Did we get roughly the number of vehicles we expected? 671 yesterday and 4
  today means something broke upstream.
- Are there duplicate vehicle ids in the same batch?
- Is the feed clock close to the real clock?

**Layer 3 — history checks.** Did anything change impossibly since last time?
- Did a bus teleport 50 km in 15 seconds?
- Did a bus that was moving vanish with no "trip finished" message?

**Bad rows are never deleted.** They go into a `quarantine` table with a reason.
That way we can look at them later and decide if our rule was too strict.

### 4. Operation = one command

Everything runs through `run.py`. See "How to run it" below.

---

## The modules

Each file has one job. Data flows down this list.

| Module | Job | Plain words |
|---|---|---|
| `pipeline/config.py` | Settings | All the URLs, file paths, timers and limits in one place |
| `pipeline/fetch.py` | Get | Download raw bytes from the Adelaide Metro API |
| `pipeline/parse.py` | Translate | Turn protobuf/zip bytes into plain Python rows |
| `pipeline/validate.py` | Check | Run the three layers of bad data detection |
| `pipeline/store.py` | Save | Write good rows to SQLite, bad rows to quarantine |
| `pipeline/export.py` | Share | Pull rows back out of SQLite into a CSV |
| `pipeline/runner.py` | Repeat | The timer loop that calls the above, over and over |
| `pipeline/log.py` | Record | Write what happened, so we can debug later |
| `schema.sql` | Shape | The table definitions for the database |
| `run.py` | Front door | The command you actually type |

Supporting files:

| File | Job |
|---|---|
| `gtfs_grab.py` | The first throwaway script. Proves the feeds work. Keep for reference. |
| `requirements.txt` | The one library we need |
| `tests/test_validate.py` | Tests for the bad data rules |

### How a single fetch flows

```
run.py
  └─ runner.py          "it has been 15 seconds, go"
       ├─ fetch.py      download the bytes
       ├─ parse.py      bytes  ->  list of rows
       ├─ validate.py   rows   ->  (good rows, bad rows)
       ├─ store.py      good rows -> gtfs.db
       │                bad rows  -> quarantine table
       └─ log.py        "671 rows in, 668 good, 3 quarantined"
```

---

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## How to run it

```bash
# Set up the database. Run this once, first.
.venv/bin/python run.py init

# Grab every feed one time and stop. Good for testing.
.venv/bin/python run.py once

# The real thing. Runs forever, on the timers above. Ctrl-C to stop.
.venv/bin/python run.py loop

# Download the static timetable (routes, stops, scheduled times).
.venv/bin/python run.py static

# See what has been collected and what got quarantined.
.venv/bin/python run.py status

# Pull data back out as a CSV.
.venv/bin/python run.py export vehicle_positions --out data/exports/vehicles.csv
```

---

## Where things end up

```
data/
├── gtfs.db              the database, everything lives here
├── exports/             CSVs we made for other people
├── static_1698/         the timetable, unzipped (from gtfs_grab.py)
└── logs/                what the pipeline did, day by day
```

---

## Not doing (on purpose)

Keeping this a prototype, so we are skipping:

- No server or web API. Query the database file directly.
- No dashboard or charts.
- No cloud, no Docker. It runs on a laptop.
- No retry queue. If a fetch fails we log it and try again on the next tick.
