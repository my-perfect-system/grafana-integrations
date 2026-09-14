"""Upload normalized dashboards to the instance."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from core import auth, settings, state
from helpers import dashboard, rules, transform


def _list_child_folders(client: auth.GrafanaClient, parent_uid: str):
    path = "/api/folders"
    if parent_uid:
        path += f"?parentUid={parent_uid}"
    return client.request_json("GET", path) or []


def _all_folders(client: auth.GrafanaClient) -> dict[str, str]:
    """Return ``{folder_path: uid}`` for the whole remote folder tree."""
    folders: dict[str, str] = {}

    def walk(parent_uid: str = "", prefix: str = "") -> None:
        for folder in _list_child_folders(client, parent_uid):
            title = folder.get("title", "")
            path = f"{prefix}/{title}" if prefix else title
            folders[path] = folder.get("uid", "")
            walk(folder.get("uid", ""), path)

    walk()
    return folders


def _local_folder_paths(source: Path) -> set[str]:
    """All non-hidden subdirectory paths under ``source`` (relative, POSIX)."""
    paths: set[str] = set()
    if not source.exists():
        return paths
    for p in source.rglob("*"):
        if not p.is_dir():
            continue
        rel = p.relative_to(source)
        if any(part.startswith(".") for part in rel.parts):
            continue
        paths.add(rel.as_posix())
    return paths


def ensure_folders(
    client: auth.GrafanaClient, paths: set[str], dry_run: bool = False
) -> tuple[dict[str, str], list[str]]:
    """Ensure every given ``/``-separated folder path exists remotely.

    Parents are created before children (via ``parentUid``) so the Grafana
    folder hierarchy mirrors the local directory structure. Returns the
    ``{path: uid}`` map (including folders that already existed) and the list
    of paths that were (or, in dry-run, would be) created.
    """
    folders = _all_folders(client)
    created: list[str] = []
    for path in sorted({p for p in paths if p}, key=lambda p: (p.count("/"), p)):
        if path in folders:
            continue
        parent_path, _, title = path.rpartition("/")
        parent_uid = folders.get(parent_path, "")
        if dry_run:
            folders[path] = ""
            created.append(path)
            continue
        payload = {"title": title}
        if parent_uid:
            payload["parentUid"] = parent_uid
        folder = client.request_json("POST", "/api/folders", json=payload) or {}
        folders[path] = folder.get("uid", "")
        created.append(path)
    return folders, created


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
        try:
            rel = path.resolve().relative_to(source.resolve())
            folder = "" if rel.parent == Path(".") else rel.parent.as_posix()
        except ValueError:
            pass
        return [(folder, path)]
    if args.folder:
        return [(args.folder, p) for p in sorted((source / args.folder).glob("*.json"))]
    if args.all:
        files = []
        for p in sorted(source.rglob("*.json")):
            rel = p.relative_to(source)
            folder = "" if rel.parent == Path(".") else rel.parent.as_posix()
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
    type_to_uid = state.datasource_type_to_uid()
    if not type_to_uid:
        print(
            "warning: no datasource snapshot (run 'discover'); "
            "datasource placeholders will be uploaded unresolved",
            file=sys.stderr,
        )

    # Phase 1: mirror the local directory tree into Grafana folders, then keep
    # the exact {path: uid} map for the upload phase.
    folder_paths = {folder for folder, _ in files} | _local_folder_paths(
        Path(args.source)
    )
    folder_map, created_folders = ensure_folders(client, folder_paths, args.dry_run)
    if created_folders:
        action = "would create" if args.dry_run else "created"
        print(f"folders {action} ({len(created_folders)}):")
        for path in created_folders:
            print(f"  + {path}")
    print(f"folder tree resolved: {len(folder_paths)} path(s)")

    # Phase 2: upload each dashboard into its pre-resolved folder.
    ok, failed = 0, 0
    seen_uids: dict[str, str] = {}
    for folder_name, path in files:
        try:
            doc = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            print(f"error reading {path}: {exc}", file=sys.stderr)
            failed += 1
            continue

        transform.normalize_datasources(doc, rules.DATASOURCE_ALIASES, type_to_uid)
        if dashboard.is_v2_dashboard(doc):
            # Drop server-side metadata (uid/resourceVersion/...) so the PUT
            # doesn't fail its UID precondition against the stored object.
            transform.clean_v2_metadata(doc)
        else:
            transform.clean_classic(doc)
            if not doc.get("uid"):
                doc["uid"] = str(
                    uuid.uuid5(uuid.NAMESPACE_DNS, f"{folder_name}/{path.name}")
                )

        title = dashboard.dashboard_title(doc)
        fmt = "v2" if dashboard.is_v2_dashboard(doc) else "classic"
        uid = doc.get("uid") or ((doc.get("metadata") or {}).get("name"))
        display = f"{folder_name}/{path.name}" if folder_name else path.name

        # Two local files may share a uid; reassign deterministically so both
        # survive instead of overwriting each other.
        if uid:
            if uid in seen_uids:
                new_uid = str(
                    uuid.uuid5(uuid.NAMESPACE_DNS, f"{folder_name}/{path.name}")
                )
                if dashboard.is_v2_dashboard(doc):
                    doc["metadata"]["name"] = new_uid
                else:
                    doc["uid"] = new_uid
                print(f"  note: duplicate uid {uid!r} -> {new_uid}")
                uid = new_uid
            seen_uids[uid] = display

        print(f"{title!r}  [{fmt}]  {display}")
        print(
            f"  uid={uid}  folder={folder_name or '(root)'}  "
            f"folderUid={folder_map.get(folder_name, '') or '-'}"
        )

        if args.dry_run:
            ok += 1
            continue

        try:
            folder_uid = folder_map.get(folder_name, "")

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
