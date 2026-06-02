"""Project LS1 contract fields into a compact dict for reviewers (no recomputation)."""

from __future__ import annotations

from hyperion_ls1_research.ls1_contract.schema import LS1_REQUIRED_PATHS, dig


def project_ls1_facts(snap: dict) -> dict:
    """Extract only public LS1 paths from an existing snapshot dict."""
    return {path: dig(snap, path) for path in LS1_REQUIRED_PATHS}