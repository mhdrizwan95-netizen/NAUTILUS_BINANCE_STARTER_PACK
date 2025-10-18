# ops/portfolio_collector.py
from __future__ import annotations
import os, asyncio, time, math, logging, httpx
from datetime import datetime, timezone
from prometheus_client import Gauge
from ops.prometheus import REGISTRY

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

PORTFOLIO_EQUITY = Gauge(
    "portfolio_equity_usd",
    "Total portfolio equity (USD)",
    registry=REGISTRY,
    multiprocess_mode="max",
)
PORTFOLIO_CASH = Gauge(
    "portfolio_cash_usd",
    "Total portfolio cash (USD)",
    registry=REGISTRY,
    multiprocess_mode="max",
)
PORTFOLIO_GAIN = Gauge(
    "portfolio_gain_usd",
    "Gain/Loss since prior close or start-of-day (USD)",
    registry=REGISTRY,
    multiprocess_mode="max",
)
PORTFOLIO_RET = Gauge(
    "portfolio_return_pct",
    "Return % since prior close or start-of-day",
    registry=REGISTRY,
    multiprocess_mode="max",
)
PORTFOLIO_PREV = Gauge(
    "portfolio_equity_prev_close_usd",
    "Baseline equity used for gain/return calc",
    registry=REGISTRY,
    multiprocess_mode="max",
)
PORTFOLIO_LAST = Gauge(
    "ops_portfolio_last_refresh_epoch",
    "Unix time of last portfolio refresh",
    registry=REGISTRY,
    multiprocess_mode="max",
)

# persistence (in-memory) for daily baseline
_BASELINE_EQUITY: float | None = None
_BASELINE_DAYKEY: str | None = None

def _daykey_now(t: float | None = None) -> str:
    dt = datetime.fromtimestamp(t or time.time(), tz=timezone.utc)
    return dt.strftime("%Y-%m-%d")

async def _fetch_snapshot(client: httpx.AsyncClient, base_url: str) -> dict:
    """Prefer /portfolio (cached/local) to avoid hammering the venue; fallback to /account_snapshot."""
    base = base_url.rstrip('/')
    # 1) Try lightweight portfolio endpoint first (does not hit venue)
    try:
        r = await client.get(f"{base}/portfolio", timeout=6.0)
        r.raise_for_status()
        return r.json()
    except Exception:
        pass
    # 2) Fallback to account_snapshot if portfolio fails
    try:
        r = await client.get(f"{base}/account_snapshot", timeout=6.0)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}

def _sumf(values):
    return float(sum(float(v or 0.0) for v in values))


async def _fetch_pnl(client: httpx.AsyncClient, base_url: str) -> dict:
    """
    Backwards-compatible helper that mirrors the PnL collector's signature.
    Delegates to `_fetch_snapshot` so existing code/tests can reuse
    the same import without duplicating logic.
    """
    return await _fetch_snapshot(client, base_url)

async def portfolio_collector_loop(interval_sec: int = 10):
    """
    Aggregates equity/cash across all engines and computes:
      - portfolio_equity_usd
      - portfolio_cash_usd
      - portfolio_gain_usd (vs start-of-day baseline)
      - portfolio_return_pct
    Baseline resets at UTC midnight or if not yet set.
    """
    global _BASELINE_EQUITY, _BASELINE_DAYKEY

    endpoints = [e.strip() for e in os.getenv(
        "ENGINE_ENDPOINTS",
        "http://engine_binance:8003,http://engine_ibkr:8005"
    ).split(",") if e.strip()]

    while True:
        try:
            async with httpx.AsyncClient() as client:
                results = await asyncio.gather(*[_fetch_snapshot(client, e) for e in endpoints], return_exceptions=True)

            equities, cashes = [], []
            for res in results:
                if not isinstance(res, dict): continue
                equities.append(res.get("equity_usd") or res.get("equity") or 0.0)
                # prefer explicit cash if available; else derive: equity - exposure - unrealized (best-effort)
                cash_val = res.get("cash_usd")
                if cash_val is None:
                    pnl = res.get("pnl") or {}
                    unrl = float(pnl.get("unrealized", 0.0))
                    exposure = 0.0
                    for p in (res.get("positions") or []):
                        qty = float(p.get("qty_base") or 0.0)
                        last = float(p.get("last_price_quote") or p.get("last") or 0.0)
                        exposure += qty * last
                    # cash ≈ equity - exposure - unrealized
                    cash_val = float((res.get("equity_usd") or 0.0) - exposure - unrl)
                cashes.append(cash_val)

            total_equity = _sumf(equities)
            total_cash   = _sumf(cashes)

            PORTFOLIO_EQUITY.set(total_equity)
            PORTFOLIO_CASH.set(total_cash)

            # Baseline logic: reset on new UTC day or if missing
            now = time.time()
            daykey = _daykey_now(now)
            if _BASELINE_DAYKEY != daykey or _BASELINE_EQUITY is None or _BASELINE_EQUITY <= 0:
                _BASELINE_EQUITY = total_equity
                _BASELINE_DAYKEY = daykey
            PORTFOLIO_PREV.set(_BASELINE_EQUITY)

            gain = total_equity - (_BASELINE_EQUITY or 0.0)
            PORTFOLIO_GAIN.set(gain)

            ret = 0.0
            if _BASELINE_EQUITY and _BASELINE_EQUITY > 0:
                ret = (gain / _BASELINE_EQUITY) * 100.0
            PORTFOLIO_RET.set(ret)

            PORTFOLIO_LAST.set(now)
            try:
                logging.info(
                    f"Portfolio totals updated: equity={total_equity:.2f} cash={total_cash:.2f}"
                )
            except Exception:
                pass
        except Exception as e:
            logging.warning(f"Portfolio collector error: {e}")

        await asyncio.sleep(interval_sec)
