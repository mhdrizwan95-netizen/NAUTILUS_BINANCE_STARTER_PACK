import sys
import os
from pathlib import Path

def check():
    print("🛡️  INITIATING SYSTEM INTEGRITY CHECK...", flush=True)
    
    # 1. File System Integrity
    required = [
        "engine/app.py",
        "engine/core/binance.py",
        "engine/core/portfolio.py",
        "engine/strategies/trend_follow.py",
        "ops/main.py"
    ]
    for r in required:
        if not Path(r).exists():
            print(f"❌ CRITICAL MISSING FILE: {r}", flush=True)
            sys.exit(1)
            
    # 2. Import Integrity (Catches broken imports from deleted files)
    try:
        print("   Verifying Imports...", flush=True)
        import engine.app
        import engine.core.order_router
        import engine.strategies.trend_follow
    except ImportError as e:
        print(f"❌ IMPORT ERROR: {e}", flush=True)
        print("   (You likely deleted a file that is still imported somewhere)", flush=True)
        sys.exit(1)

    # 3. Configuration Check
    try:
        from engine.config import get_settings
        s = get_settings()
        if s.venue.upper() != "BINANCE":
             print(f"❌ CONFIG ERROR: Venue must be BINANCE, found {s.venue}", flush=True)
             sys.exit(1)
    except Exception as e:
        print(f"❌ CONFIG LOAD FAILED: {e}", flush=True)
        sys.exit(1)

    print("✅ SYSTEM INTEGRITY VERIFIED. READY FOR DEPLOYMENT.", flush=True)

if __name__ == "__main__":
    check()
