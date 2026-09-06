"""Upload normalized dashboards to the instance."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from core import auth, settings
from helpers import dashboard


def ensure_grafana_folder(client: auth.GrafanaClient, name: str):
    if not name:
        return {"uid": "", "title": ""}
    folders = client.request_json("GET", "/api/folders") or []
    for folder in folders:
        if folder.get("title") == name:
            return folder
    created = client.request_json("POST", "/api/folders", json={"title": name})
    return created or {"uid": "", "title": name}


def _get_existing(client: auth.GrafanaClient, namespace: str, uid: str):
    path = f"/apis/dashboard.grafana.app/v2/namespaces/{namespace}/dashboards/{uid}"
    try:
        return client.request_json("GET", path)
    except auth.GrafanaError as exc:
        if getattr(exc, "status_code", None) == 404:
            return None
        raise


def upload_v2(
    client: auth.GrafanaClient, doc: dict, folder_uid: str, namespace: str = "default"
):
    meta = doc.setdefault("metadata", {})
    uid = meta.get("name")
    if not uid:
        raise auth.GrafanaError("v2 dashboard missing metadata.name (dashboard UID)")
    meta.setdefault("annotations", {})["grafana.app/folder"] = folder_uid or ""

    base = f"/apis/dashboard.grafana.app/v2/namespaces/{namespace}/dashboards"
    existing = _get_existing(client, namespace, uid)
    if existing is not None:
        prev_labels = (existing.get("metadata") or {}).get("labels") or {}
        if "grafana.app/deprecatedInternalID" in prev_labels:
            meta.setdefault("labels", {})["grafana.app/deprecatedInternalID"] = (
                prev_labels["grafana.app/deprecatedInternalID"]
            )
        return client.request_json("PUT", f"{base}/{uid}", json=doc)
    return client.request_json("POST", base, json=doc)


def upload_classic(client: auth.GrafanaClient, doc: dict, folder_uid: str):
    payload = {
        "dashboard": doc,
        "folderUid": folder_uid or "",
        "overwrite": True,
        "message": "uploaded via grafana-integrations helper script",
    }
    return client.request_json("POST", "/api/dashboards/db", json=payload)


def _collect_files(args) -> list[tuple[str, Path]]:
    source = Path(args.source)
    if args.file:
        path = Path(args.file)
        folder = path.parent.name
        if path.parent.resolve() == source.resolve():
            folder = ""
        return [(folder, path)]
    if args.folder:
        return [(args.folder, p) for p in sorted((source / args.folder).glob("*.json"))]
    if args.all:
        files = []
        for p in sorted(source.rglob("*.json")):
            rel = p.relative_to(source)
            folder = rel.parent.name if str(rel.parent) != "." else ""
            files.append((folder, p))
        return files
    return []


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "upload",
        help="Upload normalized dashboards to Grafana",
        description="Upload dashboards/normalized/ to the instance, mirroring "
        "subfolders as Grafana folders.",
    )
    p.add_argument(
        "--all", action="store_true", help="Upload every normalized dashboard."
    )
    p.add_argument("--file", help="Upload a single normalized dashboard file.")
    p.add_argument("--folder", help="Upload only dashboards under this subfolder.")
    p.add_argument(
        "--source",
        default=str(settings.NORMALIZED_DIR),
        help="Directory of normalized dashboards (default: normalized/).",
    )
    p.add_argument(
        "--namespace",
        default="default",
        help="K8s namespace for v2 uploads (OSS default: 'default').",
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
    folder_cache: dict[str, str] = {}

    ok, failed = 0, 0
    for folder_name, path in files:
        try:
            doc = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            print(f"error reading {path}: {exc}", file=sys.stderr)
            failed += 1
            continue

        title = dashboard.dashboard_title(doc)
        fmt = "v2" if dashboard.is_v2_dashboard(doc) else "classic"
        uid = doc.get("uid") or ((doc.get("metadata") or {}).get("name"))
        display = path.name if folder_name else f"{folder_name}/{path.name}"

        print(f"{title!r}  [{fmt}]  {display}")
        print(f"  uid={uid}  folder={folder_name or '(root)'}")

        if args.dry_run:
            ok += 1
            continue

        try:
            if folder_name not in folder_cache:
                folder_cache[folder_name] = ensure_grafana_folder(
                    client, folder_name
                ).get("uid", "")
            folder_uid = folder_cache[folder_name]

            if dashboard.is_v2_dashboard(doc):
                upload_v2(client, doc, folder_uid, args.namespace)
            else:
                upload_classic(client, doc, folder_uid)
            print("  -> uploaded")
            ok += 1
        except auth.GrafanaError as exc:
            print(f"  -> FAILED: {exc}", file=sys.stderr)
            failed += 1

    print()
    print(f"uploaded: {ok}  failed: {failed}" + ("  (dry-run)" if args.dry_run else ""))
    return 0 if failed == 0 else 1
