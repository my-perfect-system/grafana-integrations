"""Reading and understanding dashboard JSON (both v2 and classic formats)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_EXPR_KEYS = ("expr",)

# Datasource references that are Grafana built-ins, not instance datasources.
_BUILTIN_DATASOURCES = {"grafana", "-- Grafana --", ""}

# PromQL function / operator / modifier keywords that must NOT be mistaken for
# metric names when extracting from an expression.
_FUNCTIONS = set(
    """
abs absent absent_over_time acos acosh asin asinh atan atanh atan2
avg_over_time ceil changes clamp clamp_max clamp_min cos cosh
count_over_time days_in_month day_of_month day_of_week day_of_year deg
delta deriv double_exponential_smoothing exp floor histogram_avg
histogram_count histogram_fraction histogram_quantile histogram_stddev
histogram_stdvar histogram_sum holt_winters hour idelta increase info
irate label_join label_replace last_over_time ln log10 log2 mad_over_time
max_over_time min_over_time minute month pi predict_linear present_over_time
quantile_over_time rad rate resets round scalar sgn sin sinh sort
sort_by_label sort_by_label_desc sqrt stddev_over_time stdvar_over_time
sum_over_time tan tanh time timestamp vector year
sum avg count max min group stddev stdvar count_values quantile topk
bottomk limitk limit_ratio sort_desc sort_asc
""".split()
)

_KEYWORDS = set(
    """
by without on ignoring group_left group_right offset bool and or unless at
start end
""".split()
)


def is_v2_dashboard(doc: dict) -> bool:
    """Return True if ``doc`` uses the Grafana v13 K8s provisioning format."""
    return doc.get("kind") == "Dashboard" and str(doc.get("apiVersion", "")).startswith(
        "dashboard.grafana.app/"
    )


def extract_expressions(doc: dict) -> list[str]:
    """Return every PromQL expression/query string found in the dashboard."""
    found: list[str] = []

    def walk(o) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k in _EXPR_KEYS and isinstance(v, str) and v.strip():
                    found.append(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for item in o:
                walk(item)

    walk(doc)
    return found


def extract_metric_names(expr: str) -> list[str]:
    """Return the metric names referenced in a single PromQL expression.

    Strips quoted strings, ``$``-variables, aggregation/grouping clauses,
    duration literals and label matchers so only metric identifiers remain.
    One expression can yield several names.
    """
    cleaned = re.sub(r'"[^"]*"|\'[^\']*\'', " ", expr)
    cleaned = re.sub(r"\$[a-zA-Z_][a-zA-Z0-9_]*", " ", cleaned)
    cleaned = re.sub(
        r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)", " ", cleaned
    )
    cleaned = re.sub(r"\b\d+(?:\.\d+)?(?:ms|µs|us|s|m|h|d|w|y)\b", " ", cleaned)

    label_names = set(
        re.findall(r"([a-zA-Z_:][a-zA-Z0-9_:]*)\s*(?:!~|=~|!=|=)", cleaned)
    )

    names: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[a-zA-Z_:][a-zA-Z0-9_:]*", cleaned):
        if token in _FUNCTIONS or token in _KEYWORDS or token in label_names:
            continue
        if token not in seen:
            seen.add(token)
            names.append(token)
    return names


def extract_datasource_refs(doc: dict) -> set[str]:
    """Return the set of datasource UIDs referenced by the dashboard."""
    refs: set[str] = set()

    def walk(o) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "datasource":
                    if isinstance(v, str):
                        refs.add(v)
                    elif isinstance(v, dict):
                        if v.get("name") is not None:
                            refs.add(v["name"])
                        elif v.get("uid") is not None:
                            refs.add(v["uid"])
                else:
                    walk(v)
        elif isinstance(o, list):
            for item in o:
                walk(item)

    walk(doc)
    return refs - _BUILTIN_DATASOURCES


def get_dashboard_uid(doc: dict) -> str | None:
    """Return the user-facing dashboard UID (metadata.name for v2, uid otherwise)."""
    if is_v2_dashboard(doc):
        return (doc.get("metadata") or {}).get("name")
    return doc.get("uid")


def set_dashboard_uid(doc: dict, new_uid: str) -> None:
    if is_v2_dashboard(doc):
        doc.setdefault("metadata", {})["name"] = new_uid
    else:
        doc["uid"] = new_uid


def dashboard_title(doc: dict) -> str:
    if is_v2_dashboard(doc):
        return (doc.get("spec") or {}).get("title", "?")
    return doc.get("title", "?")


def load_dashboards(source_dir: Path) -> list[tuple[str, str, dict]]:
    """Return ``(subfolder, filename, doc)`` for every JSON under ``source_dir``."""
    results: list[tuple[str, str, dict]] = []
    for path in sorted(Path(source_dir).rglob("*.json")):
        try:
            doc = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            print(f"warning: skipping {path}: {exc}", file=sys.stderr)
            continue
        results.append((path.parent.name, path.name, doc))
    return results


def write_normalized(
    subfolder: str, filename: str, doc: dict, output_dir: Path
) -> Path:
    out = Path(output_dir) / subfolder / filename
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n")
    return out
