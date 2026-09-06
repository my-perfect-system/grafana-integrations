"""Grafana dashboard integration toolkit.

Structured as:

    core/      - configuration, auth client, state snapshots
    helpers/   - dashboard parsing and normalization transforms
    commands/  - CLI subcommands (discover, metrics, normalize, upload, verify, check)

Run via ``python -m src <command>`` or ``python src/cli.py <command>``.
"""
