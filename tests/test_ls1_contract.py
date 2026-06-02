import pytest

from hyperion_ls1_research.ls1_contract import load_snapshot, validate_snapshot
from hyperion_ls1_research.ls1_contract.projection import project_ls1_facts


@pytest.mark.parametrize(
    "name",
    [
        "dongshan_missed_entry",
        "xinyisheng_healthy_washout",
        "xinyuan_false_breakout",
    ],
)
def test_fixture_validates_required_ls1_fields(name: str):
    snap = load_snapshot(name)
    report = validate_snapshot(snap)
    assert report["ok"], report


def test_project_ls1_facts_does_not_mutate_snapshot():
    snap = load_snapshot("dongshan_missed_entry")
    before = snap.copy()
    facts = project_ls1_facts(snap)
    assert snap == before
    assert facts["ls1_supercharged.spring.launch"] is True