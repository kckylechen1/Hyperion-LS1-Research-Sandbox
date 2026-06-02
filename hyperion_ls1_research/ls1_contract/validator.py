"""Validate fixture snapshots expose the public LS1 contract fields."""

from __future__ import annotations

from hyperion_ls1_research.ls1_contract.schema import (
    LS1_REQUIRED_PATHS,
    SNAPSHOT_ENVELOPE_KEYS,
    dig,
)


def validate_snapshot_envelope(snap: dict) -> list[str]:
    errors: list[str] = []
    for key in SNAPSHOT_ENVELOPE_KEYS:
        if key not in snap:
            errors.append(f"missing envelope key: {key}")
    return errors


def _path_exists(snap: dict, path: str) -> bool:
    cur: object = snap
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return False
        cur = cur[key]
    return True


def validate_ls1_contract(snap: dict) -> list[str]:
    """Return list of missing LS1 paths (empty = OK). Values may be null."""
    missing: list[str] = []
    for path in LS1_REQUIRED_PATHS:
        if not _path_exists(snap, path):
            missing.append(path)
    return missing


def validate_snapshot(snap: dict) -> dict:
    envelope_errors = validate_snapshot_envelope(snap)
    ls1_missing = validate_ls1_contract(snap)
    return {
        "ok": not envelope_errors and not ls1_missing,
        "envelope_errors": envelope_errors,
        "ls1_missing": ls1_missing,
    }