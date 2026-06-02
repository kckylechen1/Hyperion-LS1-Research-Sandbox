import inspect

from hyperion_ls1_research.alpha_tensor import PHYSICS_RECOMPUTE_FORBIDDEN, build_alpha_tensor
from hyperion_ls1_research.alpha_tensor.builder import build_alpha_tensor as _builder
from hyperion_ls1_research.ls1_contract import load_snapshot


def test_builder_does_not_import_warpcore_or_recompute():
    src = inspect.getsource(_builder)
    assert "import warpcore" not in src
    assert "import torch" not in src
    assert PHYSICS_RECOMPUTE_FORBIDDEN


def test_missed_entry_ignition_visible_in_alpha():
    snap = load_snapshot("dongshan_missed_entry")
    alpha = build_alpha_tensor(snap)
    assert alpha.ignition.ignition_bar_present is True
    assert alpha.v8_grade == "C"


def test_false_breakout_trap_surfaces_in_risk():
    snap = load_snapshot("xinyuan_false_breakout")
    alpha = build_alpha_tensor(snap)
    assert alpha.risk.is_trap is True
    assert alpha.is_lethal() or alpha.risk.overheat_index >= 5