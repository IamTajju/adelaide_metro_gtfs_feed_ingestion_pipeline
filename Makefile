# Pipeline commands. Run from the repository root.
PYTHON = venv/bin/python

.PHONY: candidates selection

# T02: route candidates (top N_CANDIDATES by CBD boardings); map them.
candidates:
	$(PYTHON) -m select_routes

# Pick the top k routes from the latest route candidates (weighted rank + N/E/S/W coverage).
selection:
	$(PYTHON) -m select_routes.selection
