"""Test connectivity and authentication to the Grafana instance."""

from __future__ import annotations

import sys

from core import auth


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "check",
        help="Test connectivity and auth to Grafana",
        description="Validate GRAFANA_URL/GRAFANA_TOKEN against /api/health and /api/org.",
    )
    p.set_defaults(func=main)


def main(args) -> int:
    try:
        client = auth.get_client()
        info = auth.check_connection(client)
    except auth.GrafanaError as exc:
        print(f"connection failed: {exc}", file=sys.stderr)
        return 1

    print("Grafana connection OK")
    print(f"  url:      {auth.GRAFANA_URL}")
    print(f"  version:  {info['version']}  (db: {info['database']})")
    print(f"  org:      {info['org_name']} (id={info['org_id']})")
    return 0
