"""Persistence of discovery/metrics snapshots under ``data/state``."""

from __future__ import annotations

import json
from pathlib import Path

from core import settings
from core.auth import GrafanaError


def save_state(path, payload) -> None:
    """Write a snapshot as indented JSON to ``path`` (creating parents)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def load_state(path):
    """Return the parsed JSON at ``path``, or None if missing/invalid."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def load_discovery():
    """Return the discovery snapshot, or None."""
    return load_state(settings.DATASOURCES_STATE)


def discovery_entry(key: str):
    """Return the ``prometheus`` / ``loki`` entry from the discovery snapshot."""
    state = load_discovery()
    return state.get(key) if state else None


def resolve_datasource_uid(flag_value, key: str, label: str) -> str:
    """Resolve a datasource UID from an explicit flag or the discovery snapshot."""
    if flag_value:
        return flag_value
    entry = discovery_entry(key)
    if entry and entry.get("uid"):
        return entry["uid"]
    raise GrafanaError(
        f"No {label} datasource UID: pass a --*-datasource flag or run 'discover' first"
    )


def load_metric_names(path=settings.METRICS_STATE) -> set[str]:
    """Return the set of available metric names from the metrics snapshot."""
    state = load_state(path)
    if not state:
        return set()
    return set(state.get("metrics") or [])


def datasource_type_to_uid(path=settings.DATASOURCES_STATE) -> dict[str, str]:
    """Return ``{type: uid}`` from the discovery snapshot."""
    state = load_state(path)
    if not state:
        return {}
    return {
        d.get("type"): d.get("uid")
        for d in state.get("datasources") or []
        if d.get("type") and d.get("uid")
    }
