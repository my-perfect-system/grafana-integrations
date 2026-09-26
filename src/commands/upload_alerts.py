"""Upload Grafana alert rules to the instance.

Local alert files live under ``alerts/`` and each file describes one rule
group (Grafana Alerting provisioning format). Uploading is idempotent: the
rule group is upserted through the Alerting provisioning API, so re-running
overwrites the group's rules with the local definition.

Format
------
``alerts/<group>/<group>.json``::

    {
      "folder": "alerts/my-perfect-system/meta",
      "orgId": 1,
      "title": "alloy-health",
      "interval": 60,
      "rules": [
        {
          "uid": "alloy-target-down",
          "title": "Alloy target down",
          "condition": "C",
          "for": "5m",
          "noDataState": "NoData",
          "execErrState": "Error",
          "labels": {"severity": "critical"},
          "annotations": {"summary": "..."},
          "data": [ ... ]
        }
      ]
    }

* ``folder`` is the Grafana folder path; it is mirrored/created like
  dashboard folders. ``folderUid`` may be given instead to target a folder
  directly.
* Datasource references use aliases (``${DS_PROMETHEUS}``, ``${DS_LOKI}``);
  they are resolved from ``data/state/datasources.json`` at upload time.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from core import auth, settings, state
from helpers import rules
from commands import upload as dashboard_upload


def _collect_files(args) -> list[tuple[str, Path]]:
    source = Path(args.source)
    if args.file:
        path = Path(args.file)
        folder = path.parent.name
        try:
            rel = path.resolve().relative_to(source.resolve())
            folder = "" if rel.parent == Path(".") else rel.parent.as_posix()
        except ValueError:
            pass
        return [(folder, path)]
    if args.folder:
        base = source / args.folder
        return [(args.folder, p) for p in sorted(base.rglob("*.json"))]
    if args.all:
        out = []
        for p in sorted(source.rglob("*.json")):
            rel = p.relative_to(source)
            folder = "" if rel.parent == Path(".") else rel.parent.as_posix()
            out.append((folder, p))
        return out
    return []


def _resolve_datasource_aliases(
    obj, alias_map: dict[str, str], type_to_uid: dict[str, str]
) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in ("datasourceUid", "target_datasource_uid") and isinstance(
                value, str
            ):
                if value in alias_map and alias_map[value] in type_to_uid:
                    obj[key] = type_to_uid[alias_map[value]]
            else:
                _resolve_datasource_aliases(value, alias_map, type_to_uid)
    elif isinstance(obj, list):
        for item in obj:
            _resolve_datasource_aliases(item, alias_map, type_to_uid)


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "upload-alerts",
        help="Upload alert rules from alerts/ to Grafana",
        description="Upload alert rule groups from alerts/, mirroring the "
        "folder path as Grafana folders.",
    )
    p.add_argument("--all", action="store_true", help="Upload every alert file.")
    p.add_argument("--file", help="Upload a single alert file.")
    p.add_argument("--folder", help="Upload only alert files under this subfolder.")
    p.add_argument(
        "--source",
        default=str(settings.ALERTS_DIR),
        help="Directory of alert definitions (default: alerts/).",
    )
    p.add_argument(
        "--org-id",
        type=int,
        default=None,
        help="Org ID written into the rules (default: current org).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print intended requests without uploading.",
    )
    p.set_defaults(func=main)


def main(args) -> int:
    files = _collect_files(args)
    if not files:
        print("specify --all, --folder <name>, or --file <path>", file=sys.stderr)
        return 2

    client = auth.get_client()
    type_to_uid = state.datasource_type_to_uid()
    alias_map = dict(rules.DATASOURCE_ALIASES)
    if not type_to_uid:
        print(
            "warning: no datasource snapshot (run 'discover'); "
            "datasource aliases will be uploaded unresolved",
            file=sys.stderr,
        )

    org_id = args.org_id
    if org_id is None:
        try:
            org_id = (client.request_json("GET", "/api/org") or {}).get("id", 1)
        except auth.GrafanaError:
            org_id = 1

    # Read files first so folder paths can be pre-created (parents first).
    parsed: list[tuple[str, Path, dict | None]] = []
    folder_paths: set[str] = set()
    for local_folder, path in files:
        try:
            doc = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            print(f"error reading {path}: {exc}", file=sys.stderr)
            parsed.append((local_folder, path, None))
            continue
        folder = doc.get("folder") or local_folder
        if folder and not doc.get("folderUid"):
            folder_paths.add(folder)
        parsed.append((folder, path, doc))
    source_dir = Path(args.source)
    local_paths = dashboard_upload._local_folder_paths(source_dir)
    folder_paths |= {f"{source_dir.name}/{p}" for p in local_paths}
    folder_paths.add(source_dir.name)

    folder_map, created_folders = dashboard_upload.ensure_folders(
        client, folder_paths, args.dry_run
    )
    if created_folders:
        action = "would create" if args.dry_run else "created"
        print(f"folders {action} ({len(created_folders)}):")
        for path in created_folders:
            print(f"  + {path}")
    print(f"folder tree resolved: {len(folder_paths)} path(s)")

    ok, failed = 0, 0
    for folder, path, doc in parsed:
        if doc is None:
            failed += 1
            continue

        group_title = doc.get("title") or path.stem
        folder_uid = doc.get("folderUid") or folder_map.get(folder, "")
        interval = doc.get("interval", 60)
        rule_list = doc.get("rules") or []
        if not rule_list:
            print(f"warn: {path} has no rules, skipping", file=sys.stderr)
            continue

        for rule in rule_list:
            rule["folderUID"] = folder_uid
            rule["ruleGroup"] = group_title
            rule.setdefault("orgID", org_id)
        _resolve_datasource_aliases(rule_list, alias_map, type_to_uid)

        unresolved = sorted(
            {
                q[k]
                for r in rule_list
                for q in (r.get("data") or []) + [r.get("record") or {}]
                for k in ("datasourceUid", "target_datasource_uid")
                if isinstance(q.get(k), str)
                and q[k] in alias_map
                and alias_map[q[k]] not in type_to_uid
            }
        )
        if unresolved:
            print(
                f"warn: {group_title}: unresolved datasource aliases {unresolved} "
                "(run 'discover' first)",
                file=sys.stderr,
            )

        api_path = f"/api/v1/provisioning/folder/{folder_uid}/rule-groups/{group_title}"
        print(
            f"{group_title!r}  rules={len(rule_list)}  folder={folder or '(root)'}  uid={folder_uid or '-'}"
        )
        for rule in rule_list:
            print(f"  - {rule.get('uid') or '(no uid)'}: {rule.get('title', '')}")

        if args.dry_run:
            ok += 1
            continue

        try:
            body = {
                "title": group_title,
                "folderUid": folder_uid,
                "interval": interval,
                "rules": rule_list,
            }
            # Without this header Grafana marks the group/rules as "provisioned"
            # (provenance=api) and locks them from editing in the UI.
            client.request_json(
                "PUT", api_path, json=body, headers={"X-Disable-Provenance": "true"}
            )
            print("  -> uploaded")
            ok += 1
        except auth.GrafanaError as exc:
            print(f"  -> FAILED: {exc}", file=sys.stderr)
            failed += 1

    print()
    print(f"uploaded: {ok}  failed: {failed}" + ("  (dry-run)" if args.dry_run else ""))
    return 0 if failed == 0 else 1
