# Pipeline commands. Run from the repository root.
PYTHON = venv/bin/python

.PHONY: help selection route_candidates route_selection stop_candidates stop_selection collect

# Default target: list the commands (plain `make` downloads nothing).
help:
	@echo "make selection         run all four steps below in order"
	@echo "make route_candidates  top N_CANDIDATES routes by CBD boardings + map + bar charts"
	@echo "make route_selection   top k routes (weighted rank + N/E/S/W coverage) + map"
	@echo "make stop_candidates   CBD stops of the top k routes, with boardings"
	@echo "make stop_selection    top n stops per route + quadrant swap + CBD map"
	@echo "make collect           poll live positions of the chosen routes into data/gtfs.db (Ctrl+C to stop)"

# Stage 1 + 2: routes then stops, in order.
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

# Stage 3 (T08): poll live positions into the positions table while buses run.
collect:
	$(PYTHON) -m gtfs_position_collection
