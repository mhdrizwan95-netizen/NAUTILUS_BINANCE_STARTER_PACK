import sys
from pathlib import Path

def check():
    print("🛡️  FINAL SYSTEM CHECK...", flush=True)
    errors = []

    # 1. Zombie Check
    if Path("engine/core/kraken.py").exists():
        errors.append("CRITICAL: Zombie files detected (run force_repair.py!)")

    # 2. Portfolio Check
    try:
        from engine.core.portfolio import Portfolio
        p = Portfolio()
        if not hasattr(p.state, "balances"):
            errors.append("CRITICAL: Portfolio is still Single-Currency (run force_repair.py!)")
    except Exception as e:
        errors.append(f"Portfolio Load Error: {e}")

    # 3. Brain Check
    try:
        from engine.services.param_client import apply_dynamic_config
    except ImportError:
        errors.append("CRITICAL: ParamClient missing 'apply_dynamic_config' (run force_repair.py!)")

    # 4. Frontend Check
    try:
        ws_code = Path("frontend/src/lib/websocket.ts").read_text()
        if 'searchParams.set("session"' in ws_code:
             errors.append("CRITICAL: Frontend using 'session' instead of 'token'")
    except Exception:
        errors.append("Could not read websocket.ts")

    if errors:
        print("\n❌ SYSTEM NOT READY. FIX ERRORS:", flush=True)
        for e in errors: print(f" - {e}", flush=True)
        sys.exit(1)
    
    print("\n🚀 ALL SYSTEMS GO. AUTONOMOUS MODE ENGAGED.", flush=True)

if __name__ == "__main__":
    check()
