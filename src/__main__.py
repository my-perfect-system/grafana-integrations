"""Enable ``python -m src <command>``."""

from __future__ import annotations

import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
