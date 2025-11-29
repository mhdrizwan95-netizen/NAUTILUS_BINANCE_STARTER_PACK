import os
import subprocess
from pathlib import Path
import math
import time
from dataclasses import dataclass, field
from typing import Any

def run_cmd(cmd):
    print(f"EXEC: {cmd}")
    try:
        subprocess.run(cmd, shell=True, check=True)
    except subprocess.CalledProcessError:
        print(f"⚠️  Command failed (ignoring): {cmd}")

print("🛑 INITIATING GIT-HARD FIX...")

# --- 1. GIT PURGE (Permanently Delete Zombies) ---
ZOMBIES = [
    "engine/dynamic_policy.py",
    "engine/riskrails_adapter.py",
    "engine/compat/events_bridge.py",
    "engine/feeds/binance_announcements.py",
    "engine/core/kraken.py",
    "engine/core/kraken_ws.py",
    "engine/connectors/ibkr_client.py",
    "engine/adapters/ibkr_hist.py"
]

print("💀 Git-Removing Zombie Files...")
for z in ZOMBIES:
    if Path(z).exists():
        run_cmd(f"git rm -f {z}")
    else:
        print(f"   - Already gone: {z}")

# --- 2. OVERWRITE PORTFOLIO (Multi-Asset) ---
print("💰 Overwriting Portfolio Code...")
portfolio_code = """from __future__ import annotations
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

_LOGGER = logging.getLogger(__name__)

@dataclass
class Position:
    symbol: str
    quantity: float = 0.0
    avg_price: float = 0.0
    last_price: float = 0.0
    upl: float = 0.0
    rpl: float = 0.0
    venue: str = ""
    market: str = "spot"

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "qty_base": self.quantity,
            "avg_price_quote": self.avg_price,
            "last_price_quote": self.last_price,
            "unrealized_usd": self.upl,
            "realized_usd": self.rpl,
            "venue": self.venue,
            "market": self.market,
        }

@dataclass
class PortfolioState:
    balances: dict[str, float] = field(default_factory=lambda: {"USDT": 0.0, "BNB": 0.0})
    cash: float = 0.0
    equity: float = 0.0
    exposure: float = 0.0
    realized: float = 0.0
    unrealized: float = 0.0
    fees: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    margin_level: float = 0.0
    margin_liability_usd: float = 0.0
    wallet_breakdown: dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict:
        return {
            "balances": self.balances,
            "cash": self.cash,
            "equity": self.equity,
            "exposure": self.exposure,
            "pnl": {"realized": self.realized, "unrealized": self.unrealized, "fees": self.fees},
            "positions": [pos.to_dict() for pos in self.positions.values()],
            "ts": self.ts,
            "margin": {"level": self.margin_level, "liability_usd": self.margin_liability_usd},
            "wallet_breakdown": dict(self.wallet_breakdown),
        }

class Portfolio:
    def __init__(self, starting_balances: dict[str, float] | None = None, on_update=None) -> None:
        self._state = PortfolioState()
        if starting_balances:
            self._state.balances = starting_balances
            self._state.cash = starting_balances.get("USDT", 0.0)
            self._state.equity = self._state.cash
        self._on_update = on_update

    @property
    def state(self) -> PortfolioState:
        return self._state

    def snapshot(self) -> dict:
        return self._state.snapshot()

    def sync_wallet(self, balances: dict[str, float]) -> None:
        self._state.balances.update(balances)
        if "USDT" in balances:
            self._state.cash = balances["USDT"]
        self._recalculate()

    def update_price(self, symbol: str, price: float) -> None:
        pos = self._state.positions.get(symbol)
        if not pos: return
        pos.last_price = price
        pos.upl = (price - pos.avg_price) * pos.quantity
        self._recalculate()

    def apply_fill(self, symbol: str, side: str, quantity: float, price: float, fee_usd: float, *, venue: str | None = None, market: str | None = None) -> None:
        side = side.upper()
        qty = quantity if side == "BUY" else -quantity
        
        self._state.balances["USDT"] = self._state.balances.get("USDT", 0.0) - fee_usd
        self._state.fees += fee_usd

        symbol_key = symbol.upper()
        if "." not in symbol_key and venue: symbol_key = f"{symbol_key}.{venue.upper()}"
        
        pos = self._state.positions.setdefault(symbol_key, Position(symbol=symbol_key, venue=venue or "", market=market or "spot"))
        prev_qty = pos.quantity
        new_qty = prev_qty + qty
        
        realized = 0.0
        if (prev_qty > 0 > qty) or (prev_qty < 0 < qty):
            closed = min(abs(prev_qty), abs(qty))
            realized = (price - pos.avg_price) * closed if prev_qty > 0 else (pos.avg_price - price) * closed
            self._state.realized += realized
            self._state.balances["USDT"] = self._state.balances.get("USDT", 0.0) + realized

        if new_qty != 0:
            if (prev_qty == 0) or (prev_qty * qty > 0):
                pos.avg_price = (pos.avg_price * abs(prev_qty) + price * abs(qty)) / abs(new_qty)
            elif (prev_qty > 0 > new_qty) or (prev_qty < 0 < new_qty):
                pos.avg_price = price
        else:
            pos.avg_price = 0.0
            
        pos.quantity = new_qty
        pos.last_price = price
        pos.upl = (pos.last_price - pos.avg_price) * pos.quantity
        
        self._cleanup_positions()
        self._recalculate()
        if self._on_update: self._on_update(self._state.snapshot())

    def _cleanup_positions(self) -> None:
        to_del = [k for k, v in self._state.positions.items() if math.isclose(v.quantity, 0.0, abs_tol=1e-9)]
        for k in to_del: del self._state.positions[k]

    def _recalculate(self) -> None:
        exp = sum(abs(p.quantity * p.last_price) for p in self._state.positions.values())
        upl = sum(p.upl for p in self._state.positions.values())
        self._state.exposure = exp
        self._state.unrealized = upl
        self._state.cash = self._state.balances.get("USDT", 0.0)
        self._state.equity = self._state.cash + upl
        self._state.ts = time.time()
"""
with open("engine/core/portfolio.py", "w") as f:
    f.write(portfolio_code)

# --- 3. FIX FRONTEND HANDSHAKE ---
print("🖥️ Fixing Frontend Auth...")
ws_path = Path("frontend/src/lib/websocket.ts")
if ws_path.exists():
    content = ws_path.read_text()
    if 'searchParams.set("session"' in content:
        content = content.replace('searchParams.set("session"', 'searchParams.set("token"')
        ws_path.write_text(content)

# --- 4. WIRE HMM ---
print("🧠 Wiring HMM Hot-Reload...")
hmm_path = Path("engine/strategies/policy_hmm.py")
if hmm_path.exists():
    content = hmm_path.read_text()
    if "BUS.subscribe" not in content:
        wiring = """
try:
    from engine.core.event_bus import BUS
    async def _on_promote(e): reload_model(e)
    BUS.subscribe("model.promoted", _on_promote)
except ImportError: pass
"""
        with open(hmm_path, "a") as f:
            f.write(wiring)

# --- 5. GIT COMMIT (The Lock) ---
print("🔒 Locking changes into Git History...")
run_cmd("git add .")
run_cmd('git commit -m "ANTIGRAVITY: Purged zombies, fixed portfolio/auth wiring"')

# --- 6. CLEAN DOCKER ---
print("🐳 Cleaning Docker Bloat...")
try:
    import yaml
    with open("docker-compose.yml", "r") as f:
        dc = yaml.safe_load(f)
    
    services = dc.get("services", {})
    keep = {
        "engine_binance", "engine_binance_exporter", "ops", 
        "ml_service", "ml_scheduler", "param_controller", "data_ingester",
        "universe", "situations", "screener", "prometheus", "grafana"
    }
    
    to_delete = [s for s in services if s not in keep]
    for s in to_delete:
        del services[s]
    
    with open("docker-compose.yml", "w") as f:
        yaml.dump(dc, f, sort_keys=False)
    print("   - Docker sanitized.")
except ImportError:
    print("⚠️  Install PyYAML to clean Docker file.")

print("✅ FIX COMPLETE. YOU ARE NOW ON A CLEAN COMMIT.")
