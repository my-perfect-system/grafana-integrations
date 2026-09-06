"""Normalization transforms applied to dashboard documents."""

from __future__ import annotations

import json
import re

from helpers.dashboard import is_v2_dashboard


def apply_replacements(doc: dict, replacements: list[tuple[str, str]]) -> int:
    """Replace ``find`` with ``replace`` (word boundaries) in every string.

    Returns the number of replacements performed.
    """
    patterns = [(re.compile(rf"\b{re.escape(f)}\b"), r) for f, r in replacements]
    count = 0

    def walk(o) -> None:
        nonlocal count
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str):
                    new = v
                    for pattern, repl in patterns:
                        new, n = pattern.subn(repl, new)
                        count += n
                    o[k] = new
                else:
                    walk(v)
        elif isinstance(o, list):
            for item in o:
                walk(item)

    walk(doc)
    return count


def normalize_datasources(
    doc: dict, aliases: list[tuple[str, str]], type_to_uid: dict[str, str]
) -> None:
    """Rewrite datasource references to the real UIDs (both formats)."""
    alias_map = dict(aliases)

    def rewrite_string(value: str):
        if value in alias_map and alias_map[value] in type_to_uid:
            ds_type = alias_map[value]
            return {"type": ds_type, "uid": type_to_uid[ds_type]}
        return value

    def rewrite_object(ref: dict):
        name = ref.get("name")
        if name is not None:
            # v2 format: {"name": "<uid or variable>"}
            if name in alias_map and alias_map[name] in type_to_uid:
                ref["name"] = type_to_uid[alias_map[name]]
            return ref
        uid, ds_type = ref.get("uid"), ref.get("type")
        if ds_type == "grafana" or uid == "-- Grafana --":
            return ref  # built-in annotations
        if uid in alias_map and alias_map[uid] in type_to_uid:
            ref["type"] = alias_map[uid]
            ref["uid"] = type_to_uid[alias_map[uid]]
        return ref

    def walk(o) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "datasource":
                    if isinstance(v, str):
                        o[k] = rewrite_string(v)
                    elif isinstance(v, dict):
                        o[k] = rewrite_object(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for item in o:
                walk(item)

    walk(doc)


def remove_unused_datasource_variables(doc: dict) -> None:
    """Drop datasource template variables that nothing references anymore.

    After datasource references are rewritten to concrete UIDs, a
    ``DatasourceVariable`` whose name no longer appears as ``$name`` /
    ``${name}`` anywhere in the document is dead weight and is removed.
    """
    raw = json.dumps(doc)

    def is_referenced(name: str) -> bool:
        if not name:
            return True
        return (
            re.search(rf"\$\{{{re.escape(name)}\}}|\${re.escape(name)}\b", raw)
            is not None
        )

    if is_v2_dashboard(doc):
        variables = doc.get("spec", {}).get("variables")
        if isinstance(variables, list):
            doc["spec"]["variables"] = [
                v
                for v in variables
                if not (
                    isinstance(v, dict)
                    and v.get("kind") == "DatasourceVariable"
                    and not is_referenced((v.get("spec") or {}).get("name", ""))
                )
            ]
    else:
        tl = doc.get("templating", {}).get("list")
        if isinstance(tl, list):
            doc["templating"]["list"] = [
                v
                for v in tl
                if not (
                    isinstance(v, dict)
                    and v.get("type") == "datasource"
                    and not is_referenced(v.get("name", ""))
                )
            ]


def clean_v2_metadata(doc: dict) -> None:
    """Strip server-side metadata from a v2 dashboard before upload."""
    if not is_v2_dashboard(doc):
        return
    meta = doc.get("metadata") or {}
    for key in (
        "resourceVersion",
        "generation",
        "creationTimestamp",
        "managedFields",
        "uid",
        "namespace",
    ):
        meta.pop(key, None)
    annotations = meta.get("annotations")
    if isinstance(annotations, dict):
        for key in (
            "grafana.app/createdBy",
            "grafana.app/updatedBy",
            "grafana.app/updatedTimestamp",
            "grafana.app/saved-from-ui",
            "grafana.app/deprecatedInternalID",
        ):
            annotations.pop(key, None)


def clean_classic(doc: dict) -> None:
    """Normalize the classic dashboard ``id`` field to null.

    Note: ``__inputs`` / ``__requires`` are intentionally left intact — we only
    rewrite datasource references, we do not strip the import metadata.
    """
    if "id" in doc:
        doc["id"] = None


def normalize_dashboard(
    doc: dict,
    replacements: list[tuple[str, str]],
    aliases: list[tuple[str, str]],
    type_to_uid: dict[str, str],
) -> int:
    """Apply every normalization rule to a single dashboard; return change count."""
    changes = apply_replacements(doc, replacements)
    normalize_datasources(doc, aliases, type_to_uid)
    remove_unused_datasource_variables(doc)
    clean_v2_metadata(doc)
    clean_classic(doc)
    return changes
