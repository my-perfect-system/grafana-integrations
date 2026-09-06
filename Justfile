# Grafana dashboard integration toolkit
#
# Usage: `just <target>`  (run `just` to list targets)

set shell := ["bash", "-uc"]

python := "python3"

# Activate the virtualenv (sourced before every command that needs it)
activate := "source .venv/bin/activate &&"

# List available targets
default:
    @just --list

# Create a virtualenv in .venv and install all requirements
setup:
    {{python}} -m venv .venv
    {{activate}} pip install --no-input -r requirements.txt

# Drop into a shell with the virtualenv activated
shell: setup
    {{activate}} bash

# Test connectivity and auth to Grafana
check: setup
    {{activate}} python -m src check

# Discover datasources/folders/version -> data/state/datasources.json
discover: setup
    {{activate}} python -m src discover

# Fetch available metric names -> data/state/metrics.json
metrics: setup
    {{activate}} python -m src metrics

# Rewrite dashboards into dashboards/normalized/
normalize: setup
    {{activate}} python -m src normalize

# Rewrite dashboards (dry-run, no files written)
normalize-dry: setup
    {{activate}} python -m src normalize --dry-run

# Cross-check normalized dashboards against instance snapshots
verify: setup
    {{activate}} python -m src verify

# Upload all normalized dashboards to Grafana
upload: setup
    {{activate}} python -m src upload --all

# Upload (dry-run, print intended requests only)
upload-dry: setup
    {{activate}} python -m src upload --all --dry-run

# Full pipeline: discover -> metrics -> normalize -> verify -> upload
# (verify is report-only here: it prints findings but never blocks the upload)
pipeline: setup
    {{activate}} python -m src discover
    {{activate}} python -m src metrics
    {{activate}} python -m src normalize
    -{{activate}} python -m src verify
    {{activate}} python -m src upload --all
