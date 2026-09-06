"""Fetch available metric names (and Loki labels) from the instance."""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone

from core import auth, settings, state


def fetch_metric_names(client: auth.GrafanaClient, datasource_uid: str) -> list[str]:
    path = f"/api/datasources/proxy/uid/{datasource_uid}/api/v1/label/__name__/values"
    data = client.request_json("GET", path)
    if not isinstance(data, dict) or data.get("status") != "success":
        error = data.get("error") if isinstance(data, dict) else data
        raise auth.GrafanaError(f"Prometheus metric query failed: {error}")
    return sorted(set(data.get("data") or []))


def fetch_loki_labels(
    client: auth.GrafanaClient, datasource_uid: str
) -> dict[str, list[str]]:
    names_path = f"/api/datasources/proxy/uid/{datasource_uid}/loki/api/v1/labels"
    names_resp = client.request_json("GET", names_path)
    if not isinstance(names_resp, dict) or names_resp.get("status") != "success":
        error = names_resp.get("error") if isinstance(names_resp, dict) else names_resp
        raise auth.GrafanaError(f"Loki labels query failed: {error}")
    label_names = names_resp.get("data") or []

    labels: dict[str, list[str]] = {}
    for name in sorted(label_names):
        values_path = f"/api/datasources/proxy/uid/{datasource_uid}/loki/api/v1/label/{name}/values"
        values_resp = client.request_json("GET", values_path)
        if isinstance(values_resp, dict) and values_resp.get("status") == "success":
            labels[name] = sorted(values_resp.get("data") or [])
    return labels


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "metrics",
        help="Fetch available metric names from the instance",
        description="Pull Prometheus metric names (and optionally Loki label "
        "values) via the datasource proxy into data/state/metrics.json.",
    )
    p.add_argument("--datasource", help="Prometheus datasource UID to query.")
    p.add_argument("--loki-datasource", help="Loki datasource UID to query.")
    p.add_argument("--pattern", help="Only keep metric names matching this regex.")
    p.add_argument(
        "--output",
        default=str(settings.METRICS_STATE),
        help="Path for the metrics snapshot JSON.",
    )
    p.set_defaults(func=main)


def main(args) -> int:
    try:
        client = auth.get_client()
        prom_uid = state.resolve_datasource_uid(
            args.datasource, "prometheus", "Prometheus"
        )
        metrics = fetch_metric_names(client, prom_uid)
    except auth.GrafanaError as exc:
        print(f"metrics failed: {exc}", file=sys.stderr)
        return 1

    if args.pattern:
        try:
            regex = re.compile(args.pattern)
        except re.error as exc:
            print(f"invalid --pattern: {exc}", file=sys.stderr)
            return 1
        before = len(metrics)
        metrics = [m for m in metrics if regex.search(m)]
        print(f"pattern '{args.pattern}' kept {len(metrics)}/{before} metrics")

    loki_labels: dict[str, list[str]] | None = None
    loki_uid: str | None = None
    if args.loki_datasource or state.discovery_entry("loki"):
        try:
            loki_uid = state.resolve_datasource_uid(
                args.loki_datasource, "loki", "Loki"
            )
            loki_labels = fetch_loki_labels(client, loki_uid)
        except auth.GrafanaError as exc:
            print(f"warning: skipping Loki labels: {exc}", file=sys.stderr)

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "url": auth.GRAFANA_URL,
        "prometheus_uid": prom_uid,
        "metric_count": len(metrics),
        "metrics": metrics,
    }
    if loki_uid and loki_labels is not None:
        snapshot["loki_uid"] = loki_uid
        snapshot["loki_labels"] = loki_labels

    state.save_state(args.output, snapshot)

    print(f"Prometheus metric names: {len(metrics)}  (uid={prom_uid})")
    if loki_uid and loki_labels is not None:
        print(f"Loki labels: {len(loki_labels)} label names  (uid={loki_uid})")
    print(f"Snapshot written to {args.output}")
    return 0
