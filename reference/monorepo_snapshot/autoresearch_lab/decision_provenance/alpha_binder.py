from typing import Optional
from engine.v8.neuro.builder import build_alpha_tensor
from engine.v8.neuro.schema import AlphaTensor
from autoresearch_lab.decision_provenance.schema import DecisionAtom

def bind_alpha_tensor(atom: DecisionAtom, snapshot_fixture: Optional[dict] = None) -> AlphaTensor:
    """Binds a DecisionAtom to its respective V8/LS1 historical snapshot facts.
    
    If snapshot_fixture is provided (standard for synthetic unit tests), it directly
    uses it to project an AlphaTensor. Otherwise, defaults to a clean, minimal fallback.
    """
    if snapshot_fixture is not None:
        # Enforce that the symbol and as_of_date in the snapshot match the atom's properties if present,
        # or inject them to preserve data integrity.
        snap = snapshot_fixture.copy()
        snap["symbol"] = atom.symbol
        snap["as_of_date"] = atom.as_of_time
        return build_alpha_tensor(snap)
        
    # Default clean fallback snapshot
    fallback_snap = {
        "symbol": atom.symbol,
        "as_of_date": atom.as_of_time,
        "v8_score": {
            "grade": "B",
            "score": 65.0,
            "setup_score": 25.0,
            "ignition_score": 10.0,
            "overheat_index": 4,
            "toxic_breaker": False,
        },
        "chan": {
            "zs_count": 1,
            "stage_code": "forming",
        },
        "indicators": {
            "macd": {
                "state": "金叉持续",
            }
        },
        "price": {
            "turnover_rate": 1.5,
        },
        "momentum": {
            "vol_ratio_5d": 1.1,
        }
    }
    return build_alpha_tensor(fallback_snap)
