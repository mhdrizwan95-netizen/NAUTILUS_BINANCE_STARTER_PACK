# M5: policy.py
from typing import Tuple, Literal

Action = Tuple[Literal["BUY","SELL","HOLD"], int, float | None]

def decide_action(state:int, conf:float, feats, ctx) -> Action:
    # TODO M5: Replace with trained GBDT/MLP (state+features -> action)
    if conf < getattr(ctx, "min_conf", 0.6):
        return ("HOLD", 0, None)
    # Simple placeholder mapping
    if state == 1:
        return ("BUY", getattr(ctx, "qty", 1), None)
    return ("HOLD", 0, None)
