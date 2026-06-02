"""Pytest hooks — optional path for reference mirror tests."""

from __future__ import annotations

import sys
from pathlib import Path

_REF_SNAPSHOT = Path(__file__).resolve().parents[1] / "reference" / "monorepo_snapshot"
if _REF_SNAPSHOT.is_dir() and str(_REF_SNAPSHOT) not in sys.path:
    sys.path.insert(0, str(_REF_SNAPSHOT))