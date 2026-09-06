"""Rewrite dashboards (datasources, metric names, cleanup)."""

from __future__ import annotations

import difflib
import json
import sys
import uuid
from pathlib import Path

from core import settings, state
from helpers import dashboard, rules, transform


def _serialize(doc: dict) -> str:
    return json.dumps(doc, indent=2) + "\n"


def _print_diff(
    subfolder: str, filename: str, original_text: str, new_text: str
) -> None:
    diff = difflib.unified_diff(
        original_text.splitlines(),
        new_text.splitlines(),
        fromfile=f"a/{subfolder}/{filename}",
        tofile=f"b/{subfolder}/{filename}",
        lineterm="",
    )
    lines = list(diff)
    if not lines:
        print("    (no changes)")
        return
    for line in lines:
        print(f"    {line}")


def _report(
    doc: dict, existing: set[str], replacements: list[tuple[str, str]], verbose: bool
) -> None:
    exprs = dashboard.extract_expressions(doc)
    used: dict[str, list[str]] = {}
    for e in exprs:
        used[e] = dashboard.extract_metric_names(e)

    all_metrics: list[str] = []
    seen: set[str] = set()
    for names in used.values():
        for n in names:
            if n not in seen:
                seen.add(n)
                all_metrics.append(n)

    print(f"    expressions: {len(exprs)}   metric names: {len(all_metrics)}")
    if verbose:
        for e, names in used.items():
            print(f"      expr: {e!r}")
            if names:
                print(f"        metrics: {', '.join(names)}")
            print()

    if not existing:
        return

    find_map = dict(replacements)
    missing = [m for m in all_metrics if m not in existing]
    if missing:
        print(f"    metrics missing on instance ({len(missing)}):")
        for m in missing:
            if m in find_map:
                print(f"      {m}  ->  {find_map[m]}  (will replace)")
            else:
                print(f"      {m}  (unknown, no replacement — review manually)")


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "normalize",
        help="Rewrite dashboards into dashboards/normalized/",
        description="Read dashboards/tested/ and write normalized copies to "
        "dashboards/normalized/, applying datasource + metric replacements and cleanup.",
    )
    p.add_argument(
        "--source",
        default=str(settings.DASHBOARDS_DIR),
        help="Directory of source dashboards (default: tested/).",
    )
    p.add_argument(
        "--output",
        default=str(settings.NORMALIZED_DIR),
        help="Directory for normalized output.",
    )
    p.add_argument(
        "--metrics",
        default=str(settings.METRICS_STATE),
        help="Path to the metrics snapshot (metrics.json).",
    )
    p.add_argument(
        "--datasources",
        default=str(settings.DATASOURCES_STATE),
        help="Path to the discovery snapshot (datasources.json).",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print each expression and its metric names.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without writing files.",
    )
    p.set_defaults(func=main)


def main(args) -> int:
    existing = state.load_metric_names(Path(args.metrics))
    type_to_uid = state.datasource_type_to_uid(Path(args.datasources))

    if not existing:
        print(
            "note: no metrics snapshot found; skipping instance comparison. "
            "Run 'metrics' first.",
            file=sys.stderr,
        )

    dashboards = dashboard.load_dashboards(Path(args.source))
    if not dashboards:
        print(f"no dashboards found under {args.source}", file=sys.stderr)
        return 1

    seen_uids: dict[str, str] = {}
    total_changes = 0

    for subfolder, filename, doc in dashboards:
        original_text = _serialize(doc)
        print(f"dashboard: {subfolder}/{filename}")
        _report(doc, existing, rules.REPLACEMENTS, args.verbose)

        uid = dashboard.get_dashboard_uid(doc)
        if uid:
            if uid in seen_uids:
                new_uid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{subfolder}/{filename}"))
                print(
                    f"    UID collision '{uid}' (also {seen_uids[uid]}); assigning {new_uid}"
                )
                dashboard.set_dashboard_uid(doc, new_uid)
                uid = new_uid
            seen_uids[uid] = f"{subfolder}/{filename}"

        changes = transform.normalize_dashboard(
            doc, rules.REPLACEMENTS, rules.DATASOURCE_ALIASES, type_to_uid
        )
        total_changes += changes
        if changes:
            print(f"    replacements applied: {changes}")

        _print_diff(subfolder, filename, original_text, _serialize(doc))

        if not args.dry_run:
            out = dashboard.write_normalized(
                subfolder, filename, doc, Path(args.output)
            )
            print(f"    wrote {out}")
        print()

    print(f"done: {len(dashboards)} dashboards, {total_changes} string replacements")
    if args.dry_run:
        print("dry-run: no files written")
    return 0
