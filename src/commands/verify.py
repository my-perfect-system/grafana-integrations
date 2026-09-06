"""Cross-check normalized dashboards against instance snapshots."""

from __future__ import annotations

import sys
from pathlib import Path

from core import settings, state
from helpers import dashboard


def extract_metric_refs(doc: dict) -> set[str]:
    names: set[str] = set()
    for expr in dashboard.extract_expressions(doc):
        names.update(dashboard.extract_metric_names(expr))
    return names


def check_against_instance(
    doc: dict, metrics: set[str] | None, datasources: set[str] | None
) -> list[str]:
    problems: list[str] = []
    if metrics is not None:
        for name in sorted(extract_metric_refs(doc)):
            if name not in metrics:
                problems.append(f"metric '{name}' not available on instance")
    if datasources is not None:
        for ref in sorted(dashboard.extract_datasource_refs(doc)):
            if ref not in datasources:
                problems.append(f"datasource uid '{ref}' not found on instance")
    return problems


def report(problems: dict[str, list[str]]) -> None:
    for name, probs in problems.items():
        if probs:
            print(f"{name}: {len(probs)} problem(s)")
            for p in probs:
                print(f"  - {p}")
        else:
            print(f"{name}: OK")


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "verify",
        help="Cross-check normalized dashboards against instance snapshots",
        description="Report metrics/datasources referenced by dashboards but not "
        "present on the instance. Exits non-zero if problems are found.",
    )
    p.add_argument(
        "--normalized-dir",
        default=str(settings.NORMALIZED_DIR),
        help="Directory of normalized dashboards to verify.",
    )
    p.add_argument(
        "--state",
        default=str(settings.STATE_DIR),
        help="Directory holding datasources.json / metrics.json.",
    )
    p.set_defaults(func=main)


def main(args) -> int:
    state_dir = Path(args.state)

    metrics: set[str] | None = None
    metrics_data = state.load_state(state_dir / "metrics.json")
    if metrics_data:
        metrics = set(metrics_data.get("metrics") or [])
    else:
        print(
            "note: no metrics snapshot; skipping metric check. Run 'metrics' first.",
            file=sys.stderr,
        )

    datasources: set[str] | None = None
    ds_data = state.load_state(state_dir / "datasources.json")
    if ds_data:
        datasources = {d.get("uid") for d in ds_data.get("datasources") or []}
    else:
        print(
            "note: no discovery snapshot; skipping datasource check. Run 'discover' first.",
            file=sys.stderr,
        )

    dashboards = dashboard.load_dashboards(Path(args.normalized_dir))
    if not dashboards:
        print(f"no dashboards found under {args.normalized_dir}", file=sys.stderr)
        return 1

    problems: dict[str, list[str]] = {}
    for subfolder, filename, doc in dashboards:
        name = f"{subfolder}/{filename}"
        problems[name] = check_against_instance(doc, metrics, datasources)

    report(problems)

    total = sum(len(p) for p in problems.values())
    print()
    if total:
        print(f"verify: {total} problem(s) across {len(dashboards)} dashboards")
        return 1
    print(f"verify: all clean ({len(dashboards)} dashboards)")
    return 0
