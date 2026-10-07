# Pipeline commands. Run from the repository root.
PYTHON = venv/bin/python

.PHONY: help install setup selection route_candidates route_selection stop_candidates stop_selection \
	collect schedule arrivals weather test

# Default target: list the commands (plain `make` downloads nothing).
help:
	@echo "make install           create venv/ and install requirements.txt"
	@echo "make setup             create data/gtfs.db and its tables (keeps existing rows)"
	@echo "make selection         run the four selection steps below in order"
	@echo "make route_candidates  top N_CANDIDATES routes by CBD boardings + map + bar charts"
	@echo "make route_selection   top k routes (weighted rank + N/E/S/W coverage) + map"
	@echo "make stop_candidates   CBD stops of the top k routes, with boardings"
	@echo "make stop_selection    top n stops per route + quadrant swap + CBD map"
	@echo "make collect           poll live positions of the chosen routes into data/gtfs.db (Ctrl+C to stop)"
	@echo "make schedule          rebuild scheduled_stop_times now (the collector also does it daily)"
	@echo "make arrivals          observed vs scheduled arrivals from the stored positions"
	@echo "make weather           hourly weather for yesterday (or DAY=YYYY-MM-DD)"
	@echo "make test              run the test suite"

# Virtual environment with the pinned dependencies.
install:
	python3 -m venv venv
	$(PYTHON) -m pip install -r requirements.txt

# Database tables (the selection and collector also create them when missing).
setup:
	$(PYTHON) -m data_collection_setup

# Stages 1 + 2: routes then stops, in order.
selection: route_candidates route_selection stop_candidates stop_selection

# Route candidates (top N_CANDIDATES by CBD boardings); route map and bar charts.
route_candidates:
	$(PYTHON) -m select_routes

# Pick the top k routes from the latest route candidates (weighted rank + N/E/S/W coverage).
route_selection:
	$(PYTHON) -m select_routes.selection

# Stop candidates (every CBD stop served by the latest top k routes).
stop_candidates:
	$(PYTHON) -m select_stops

# Top n CBD stops per route from the latest stop candidates (+ N/E/S/W quadrant swap).
stop_selection:
	$(PYTHON) -m select_stops.selection

# Stage 3: poll live positions into the positions table while buses run.
collect:
	$(PYTHON) -m gtfs_position_collection

# Stage 3: rebuild scheduled_stop_times for the chosen trips x stops (the collector also does this).
schedule:
	$(PYTHON) -m gtfs_position_collection.scheduled_times --force-reload

# Stage 3, after collection: observed vs scheduled arrivals.
arrivals:
	$(PYTHON) -m gtfs_position_collection.arrivals

# Stage 4: hourly weather for one day (default yesterday): make weather DAY=2026-10-07
weather:
	$(PYTHON) -m weather_collection $(DAY)

test:
	$(PYTHON) -m pytest tests
