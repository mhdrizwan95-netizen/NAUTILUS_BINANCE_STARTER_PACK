import sys
from engine.core.portfolio import Portfolio

def check():
    print("🔎 Verifying Fixes...", flush=True)
    
    # 1. Portfolio Check
    p = Portfolio()
    if not hasattr(p.state, "balances"):
        print("❌ FAIL: Portfolio still legacy (no 'balances')", flush=True)
        sys.exit(1)
    print("✅ Portfolio: Multi-Currency Active", flush=True)

    # 2. WS Auth Check (Static Analysis)
    with open("frontend/src/lib/websocket.ts") as f:
        content = f.read()
        if 'url.searchParams.set("token"' not in content and 'token=' not in content:
            print("❌ FAIL: Frontend WS sending 'session' not 'token'", flush=True)
            sys.exit(1)
    print("✅ Frontend: Auth Param Fixed", flush=True)
    
    print("🚀 SYSTEM READY.", flush=True)

if __name__ == "__main__":
    check()
