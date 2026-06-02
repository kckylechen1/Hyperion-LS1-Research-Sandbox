from hyperion_ls1_research.decision_provenance import bind_chat_to_snapshot
from hyperion_ls1_research.decision_provenance.validator import lesson_from_diagnosis
from hyperion_ls1_research.ls1_contract import load_chat, load_snapshot


def test_missed_entry_binds_chat_to_alpha_and_scoring_diagnosis():
    chat = load_chat("dongshan_chat")[0]
    snap = load_snapshot("dongshan_missed_entry")
    bundle, alpha, diagnosis = bind_chat_to_snapshot(chat, snap)
    assert len(bundle.watch_idea.user_intent_summary) <= 120
    assert alpha.ignition.ignition_bar_present
    assert diagnosis["diagnosis"] == "scoring_error"
    assert "aggregate" in diagnosis["answer"].lower() or "scoring" in diagnosis["answer"].lower()


def test_lesson_candidate_excludes_raw_chat():
    chat = load_chat("dongshan_chat")[0]
    snap = load_snapshot("dongshan_missed_entry")
    _, _, diagnosis = bind_chat_to_snapshot(chat, snap)
    lesson = lesson_from_diagnosis(diagnosis, "SYNTH.DS01.SH")
    assert lesson is not None
    assert chat["user_text"] not in lesson["core_axiom"]
    assert chat["agent_text"] not in lesson["core_axiom"]