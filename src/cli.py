"""Single entrypoint for the Grafana integration toolkit.

Usage
-----
    python -m src <command> [options]
    python src/cli.py <command> [options]

Commands
--------
    discover   fetch datasources/folders/version from the instance
    metrics    fetch available metric names (and Loki labels) from the instance
    normalize  rewrite dashboards (datasources, metric names, cleanup)
    verify     cross-check normalized dashboards against instance snapshots
    upload     upload normalized dashboards to the instance
    check      test connectivity and authentication

Workflow
--------
    discover -> metrics -> normalize -> verify -> upload
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure this package directory is importable whether invoked as
# `python src/cli.py` or `python -m src`.
_PKG = Path(__file__).resolve().parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from core import auth  # noqa: E402
from commands import (  # noqa: E402
    check,
    discover,
    metrics,
    normalize,
    upload,
    verify,
)

_COMMANDS = (discover, metrics, normalize, verify, upload, check)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grafana-integrations",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    for module in _COMMANDS:
        module.add_parser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    auth.load_config()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
