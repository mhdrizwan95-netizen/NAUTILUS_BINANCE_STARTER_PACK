# M5: guardrails.py
from enum import Enum

class Block(Enum):
    OK="OK"; SPREAD="SPREAD"; POS="POS"; COOLDOWN="COOLDOWN"; LATENCY="LATENCY"; DD="DD"; KILL="KILL"

def check_gates(context, now_ns, spread_bp, qty, portfolio, metrics) -> Block:
    # TODO M5: Wire to Nautilus portfolio/metrics
    if spread_bp > getattr(context.cfg, "max_spread_bp", 3.0):
        return Block.SPREAD
    return Block.OK
