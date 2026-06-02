import datetime
from engine.v8.infra import tachi_client
from engine.v8.neuro.schema import AlphaTensor
from autoresearch_lab.decision_provenance.schema import (
    DecisionAtom,
    BetaTensor,
    OutcomeMetrics,
    CausalityDiagnosis,
    DistilledLesson,
)

def promote_to_tachi(
    atom: DecisionAtom,
    alpha: AlphaTensor,
    beta: BetaTensor,
    outcome: OutcomeMetrics,
    diagnosis: CausalityDiagnosis
) -> DistilledLesson:
    """Distills the forensic analysis of a decision into an atomic lesson 
    and promotes it to HyperTachi semantic memory, strictly enforcing 
    the boundary: NO raw conversational logs or noise may be saved.
    """
    
    # 1. Unique Lesson ID and Timestamp
    timestamp_str = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    clean_sym = atom.symbol.replace(".", "_")
    lesson_id = f"LS1-{clean_sym}-{diagnosis.diagnosis.upper()}-{atom.as_of_time.replace(':', '').replace('-', '')}"
    
    # 2. Formulate core axioms based on the diagnosis type
    diag = diagnosis.diagnosis
    axiom = ""
    if diag == "beta_error":
        if beta.panic_exit:
            axiom = f"【纪律教训】大周期趋势与支撑位完好，绝不能在盘中洗盘（Washout）低点因恐慌而割肉离场。必须严格以大周期收盘或结构破位为退出信号。"
        elif alpha.is_lethal():
            axiom = f"【纪律教训】大周期指标已提示超买或微观存在高潮骗炮（Overheat={alpha.risk.overheat_index}），绝对严禁满仓追高！必须遵守分批或轻仓纪律。"
        else:
            axiom = f"【纪律教训】在面临日内波动时，必须严格执行日内T+0减仓规避短线波动，而非在持仓期不做任何对冲保护。"
    elif diag == "alpha_error":
        axiom = f"【系统教训】个股在健康的左侧和右侧共振形态下依然发生跌破，表明市场大环境出现短期风格切换（Regime={alpha.global_regime.market_regime}）或局部主力诱多出货，指标发生回撤。"
    elif diag == "scoring_error":
        axiom = f"【评分教训】V8评分系统存在钝化滞后。在个股量能微观场已经检测出骗炮/诱多风险（is_trap=True）的情况下，评分依然给出了 S/A 的高评分，需要修正评分权重。"
    elif diag == "mixed_error":
        axiom = f"【综合教训】个股本身处于量能与风险的模糊边界，同时执行端严重超重仓（Sizing={beta.sizing_discipline_pct}），在没有对冲保护的情况下，多重失误共振导致亏损。"
    else:
        axiom = f"【操作规范】在 Grade={alpha.v8_grade} 且大盘稳定的背景下，严格按照模型信号操作，交易逻辑闭环，无纪律违规。"
        
    # 3. Assemble condensed structured evidence
    evidence = (
        f"Alpha: Grade={alpha.v8_grade}, Overheat={alpha.risk.overheat_index}, is_trap={alpha.risk.is_trap} | "
        f"Beta: Sizing={beta.sizing_discipline_pct:.1f}, Panic={beta.panic_exit}, Override={beta.fundamental_override} | "
        f"Outcome: T5_ret={outcome.return_t5:.2%}, MAE={outcome.mae:.2%}, MFE={outcome.mfe:.2%}"
    )
    
    # 4. Form Pydantic model
    lesson = DistilledLesson(
        lesson_id=lesson_id,
        timestamp=timestamp_str,
        symbol=atom.symbol,
        verdict_type=diagnosis.diagnosis.upper(),
        core_axiom=axiom,
        evidence=evidence,
    )
    
    # 5. Save to HyperTachi via tachi_client (fail-safe fallback)
    text_content = (
        f"# Atomic Lesson: {lesson.lesson_id}\n\n"
        f"**Symbol**: {lesson.symbol}\n"
        f"**Verdict**: {lesson.verdict_type}\n"
        f"**Axiom**: {lesson.core_axiom}\n"
        f"**Evidence**: {lesson.evidence}\n"
    )
    
    # Strictly avoid any conversational raw text in save_memory
    if tachi_client.is_available():
        try:
            tachi_client.save_memory(
                text=text_content,
                path=f"/trading/equity/lessons/decision_provenance/{lesson.symbol}",
                id=f"provenance_lesson:{lesson.lesson_id}",
                project="hyperion",
                metadata={
                    "symbol": lesson.symbol,
                    "verdict": lesson.verdict_type,
                    "lesson_id": lesson.lesson_id,
                    "type": "decision_provenance_lesson",
                }
            )
        except Exception:
            pass # Keep it fail-safe as mandated by Tachi contract
            
    return lesson
