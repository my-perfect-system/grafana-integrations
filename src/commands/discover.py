"""Discover datasources, folders and version on the target instance."""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from core import auth, settings, state


def fetch_datasources(client: auth.GrafanaClient) -> list[dict]:
    return client.request_json("GET", "/api/datasources") or []


def fetch_folders(client: auth.GrafanaClient) -> list[dict]:
    return client.request_json("GET", "/api/folders") or []


def fetch_version(client: auth.GrafanaClient) -> str:
    health = client.request_json("GET", "/api/health") or {}
    return health.get("version", "unknown")


def pick_by_type(datasources: list[dict], ds_type: str) -> dict | None:
    matches = [d for d in datasources if d.get("type") == ds_type]
    if not matches:
        return None
    default = next((d for d in matches if d.get("isDefault")), None)
    return default or matches[0]


def resolve_datasource(
    datasources: list[dict], ds_type: str, uid: str | None, name: str | None
) -> dict | None:
    if uid:
        match = next((d for d in datasources if d.get("uid") == uid), None)
        if match is None:
            raise auth.GrafanaError(f"No datasource found with uid '{uid}'")
        return match
    if name:
        match = next((d for d in datasources if d.get("name") == name), None)
        if match is None:
            raise auth.GrafanaError(f"No datasource found with name '{name}'")
        return match
    return pick_by_type(datasources, ds_type)


def _print_datasources(datasources: list[dict]) -> None:
    if not datasources:
        print("  (no datasources found)")
        return
    for d in sorted(datasources, key=lambda x: (x.get("type", ""), x.get("name", ""))):
        default = " *" if d.get("isDefault") else "  "
        print(
            f"  {default} {d.get('type', '?'):<12} {d.get('name', '?'):<30} uid={d.get('uid', '?')}"
        )


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "discover",
        help="Discover instance datasources/folders/version",
        description="Query the instance for datasources, folders and version, "
        "then persist a snapshot to data/state/datasources.json.",
    )
    p.add_argument(
        "--output",
        default=str(settings.DATASOURCES_STATE),
        help="Path for the discovery snapshot JSON.",
    )
    p.add_argument("--prom-uid", help="Override Prometheus datasource UID.")
    p.add_argument("--prom-name", help="Override Prometheus datasource name.")
    p.add_argument("--loki-uid", help="Override Loki datasource UID.")
    p.add_argument("--loki-name", help="Override Loki datasource name.")
    p.set_defaults(func=main)


def main(args) -> int:
    try:
        client = auth.get_client()
        version = fetch_version(client)
        datasources = fetch_datasources(client)
        folders = fetch_folders(client)
    except auth.GrafanaError as exc:
        print(f"discover failed: {exc}", file=sys.stderr)
        return 1

    prom = resolve_datasource(datasources, "prometheus", args.prom_uid, args.prom_name)
    loki = resolve_datasource(datasources, "loki", args.loki_uid, args.loki_name)

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "url": auth.GRAFANA_URL,
        "version": version,
        "datasources": datasources,
        "folders": [
            {"uid": f.get("uid"), "title": f.get("title"), "id": f.get("id")}
            for f in folders
        ],
        "prometheus": {"uid": prom.get("uid"), "name": prom.get("name")}
        if prom
        else None,
        "loki": {"uid": loki.get("uid"), "name": loki.get("name")} if loki else None,
    }

    state.save_state(args.output, snapshot)

    print(f"Grafana version : {version}")
    print(f"URL             : {auth.GRAFANA_URL}")
    print("Datasources     :")
    _print_datasources(datasources)
    print()
    if prom:
        print(f"Prometheus  -> uid={prom['uid']} name={prom['name']}")
    else:
        print("Prometheus  -> NOT FOUND")
    if loki:
        print(f"Loki        -> uid={loki['uid']} name={loki['name']}")
    else:
        print("Loki        -> NOT FOUND")
    print()
    print(f"Snapshot written to {args.output}")
    return 0 if prom else 1
