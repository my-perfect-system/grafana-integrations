"""Filesystem layout and shared constants.

All paths are derived from the location of this file, so the app works no
matter where the package lives or how it is invoked.
"""

from __future__ import annotations

from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1]  # src/
REPO_ROOT = SRC_DIR.parent

DASHBOARDS_DIR = REPO_ROOT / "dashboards" / "tested"
NORMALIZED_DIR = REPO_ROOT / "dashboards" / "normalized"
STATE_DIR = REPO_ROOT / "data" / "state"

DATASOURCES_STATE = STATE_DIR / "datasources.json"
METRICS_STATE = STATE_DIR / "metrics.json"

ENV_FILE = REPO_ROOT / "data" / ".env"
