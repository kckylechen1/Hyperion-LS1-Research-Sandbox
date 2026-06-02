import re
from autoresearch_lab.decision_provenance.schema import DecisionAtom, BetaTensor

def classify_beta_tensor(atom: DecisionAtom) -> BetaTensor:
    """Classifies the semantic discipline and execution state (Beta Tensor) 
    from the raw conversational context and human actions.
    """
    text = atom.raw_text.lower()
    reply = atom.agent_reply.lower()
    action = atom.human_action.upper()
    
    # 1. Short term risk / T+0 requirements
    # Triggered if agent warns about overheat or short-term micro risk, or human discusses doing T+0
    short_term_t0 = False
    if "overheat" in reply or "超买" in reply or "过热" in reply or "做t" in text or "日内" in text:
        short_term_t0 = True
        
    # 2. Long term risk / sizing
    # Triggered if agent recommends sizing limits or warns about broad index/position sizing
    long_term_size = False
    if "仓位" in reply or "不建议满仓" in reply or "风控" in reply or "风险" in reply:
        long_term_size = True
        
    # 3. Panic exit
    panic = False
    if "慌了" in text or "怕了" in text or "砸了" in text or "割肉" in text or "急跌" in text or "panic" in text or action == "PANIC_SELL":
        panic = True
        
    # 4. Fundamental override
    fundamental = False
    if "基本面" in text or "研报" in text or "业绩" in text or "行业" in text or "override" in text:
        fundamental = True
        
    # 5. Sizing discipline percent
    sizing = 1.0
    if "半" in text or "一半" in text or "0.5" in text or "半分" in text:
        sizing = 0.5
    elif "满仓" in text or "梭哈" in text or "全仓" in text or "1.0" in text or "full" in text or action == "BUY_FULL":
        sizing = 1.0
    elif "一成" in text or "0.1" in text:
        sizing = 0.1
    elif "三成" in text or "0.3" in text:
        sizing = 0.3
        
    return BetaTensor(
        short_term_risk_should_T0=short_term_t0,
        long_term_risk_should_position_size=long_term_size,
        selling_winner_holding_loser="winner" in text and "loser" in text, # simple heuristic
        panic_exit=panic,
        fundamental_override=fundamental,
        sizing_discipline_pct=sizing,
    )

