from typing import List
from autoresearch_lab.decision_provenance.schema import OutcomeMetrics

def validate_outcome(
    symbol: str, 
    future_prices: List[float], 
    human_action: str
) -> OutcomeMetrics:
    """Calculates factual post-decision metrics (returns, MFE, MAE) 
    and determines the statistical truth of the decision outcome.
    """
    if not future_prices or len(future_prices) < 1:
        return OutcomeMetrics(outcome_label="NEUTRAL")
        
    entry = future_prices[0]
    
    # Extract step-specific prices or fallback to last known price
    p_t1 = future_prices[1] if len(future_prices) >= 2 else future_prices[-1]
    p_t5 = future_prices[5] if len(future_prices) >= 6 else future_prices[-1]
    p_t10 = future_prices[10] if len(future_prices) >= 11 else future_prices[-1]
    p_t20 = future_prices[20] if len(future_prices) >= 21 else future_prices[-1]
    
    # Calculate returns
    ret_t1 = (p_t1 - entry) / entry if entry > 0 else 0.0
    ret_t5 = (p_t5 - entry) / entry if entry > 0 else 0.0
    ret_t10 = (p_t10 - entry) / entry if entry > 0 else 0.0
    ret_t20 = (p_t20 - entry) / entry if entry > 0 else 0.0
    
    # Calculate Excursions
    max_price = max(future_prices)
    min_price = min(future_prices)
    
    mfe = (max_price - entry) / entry if entry > 0 else 0.0
    mae = (min_price - entry) / entry if entry > 0 else 0.0
    
    # Labeling rules
    action = human_action.upper()
    label = "NEUTRAL"
    
    if "BUY" in action and "NO" not in action:
        # Human/Agent entered
        if ret_t5 >= 0.02:
            label = "TRUE_POSITIVE"
        elif ret_t5 <= -0.02:
            label = "FALSE_POSITIVE"
    elif "NO_BUY" in action or "AVOID" in action:
        # Human/Agent avoided
        if ret_t5 <= -0.02:
            label = "TRUE_NEGATIVE"
        elif ret_t5 >= 0.02:
            label = "FALSE_NEGATIVE"
            
    return OutcomeMetrics(
        return_t1=ret_t1,
        return_t5=ret_t5,
        return_t10=ret_t10,
        return_t20=ret_t20,
        mfe=mfe,
        mae=mae,
        outcome_label=label,
    )
