# backtests/run_backtest.py
# M4: Backtest harness for HMMPolicyStrategy.
# Preferred: Nautilus BacktestEngine (if available). Fallback: minimal simulator.
import argparse, sys, os
from pathlib import Path
import yaml, pandas as pd, numpy as np, httpx
import math
from backtests.fills import fill_price, realized_vol_bp, FillParams
from backtests.data_quality import check_row, check_spread_jump

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.hmm_policy.config import HMMPolicyConfig
from strategies.hmm_policy.features import FeatureState, compute_features
from strategies.hmm_policy.guardrails import check_gates, Block
from strategies.hmm_policy.policy import decide_action

USE_NAUTILUS = False
try:
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.backtest.engine import BacktestEngine  # type: ignore
    USE_NAUTILUS = True
except Exception as e:
    print(f"[M4] Nautilus BacktestEngine not importable ({e}); using minimal simulator.")

def load_config(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)

def load_parquet_ticks(path: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if "ts_ns" not in df.columns:
        for c in ["ts","timestamp_ns","time_ns"]:
            if c in df.columns:
                df = df.rename(columns={c:"ts_ns"}); break
    if "ts_ns" not in df.columns:
        raise ValueError("Parquet must contain 'ts_ns' (nanoseconds).")
    return df.sort_values("ts_ns").reset_index(drop=True)

def vwap_running(prices, sizes):
    v = np.cumsum((prices * sizes).fillna(0))
    q = np.cumsum(sizes.fillna(0))
    return v / np.where(q==0, np.nan, q)

def minimal_engine(cfg: dict, out_dir: Path):
    symbol = cfg["symbol"]
    data_path = cfg["data_parquet"]
    fees_bps = float(cfg.get("fees_bps", 1.0))
    slip_bps = float(cfg.get("slippage_bps", 1.5))

    print(f"[M4-fallback] Loading parquet: {data_path}")
    df = load_parquet_ticks(data_path)

    class Book:
        def __init__(self, row):
            bid = row.get("bid_px", np.nan); ask = row.get("ask_px", np.nan)
            self.bid = bid; self.ask = ask
            self.mid = np.nanmean([bid, ask]) if np.isfinite(bid) and np.isfinite(ask) else np.nan
            self.spread_bp = float((ask - bid)/self.mid * 1e4) if np.isfinite(self.mid) else float("inf")
            self.bid_sz = row.get("bid_sz", np.nan); self.ask_sz = row.get("ask_sz", np.nan)

    if "trade_px" in df.columns and "trade_sz" in df.columns:
        df["vwap"] = vwap_running(df["trade_px"], df["trade_sz"])
    else:
        df["vwap"] = df["ask_px"].combine(df["bid_px"], np.nanmean)

    scfg = HMMPolicyConfig(instrument=symbol)
    state = FeatureState(None, None, None, None)
    qty_pos = 0.0; cash = 0.0; last_px = np.nan

    trades_log, states_log, blocks_log = [], [], []
    client = httpx.Client(base_url=os.getenv("HMM_URL","http://127.0.0.1:8010"), timeout=0.05)
    HMM_TAG = os.getenv("HMM_TAG")
    mid_hist: list[float] = []
    prev_ts_ns = None
    prev_mid = None
    prev_spread_bp = None
    dq_log = []

    for i, row in df.iterrows():
        issues, ts_ns = check_row(i, row, prev_ts_ns)
        prev_ts_ns = ts_ns
        book = Book(row)
        issues += check_spread_jump(prev_mid, prev_spread_bp, book.mid, book.spread_bp)
        if issues:
            for k in issues:
                dq_log.append({"ts_ns": ts_ns, "issue": k})
        if math.isfinite(book.mid):
            mid_hist.append(book.mid)
        vol_bp = realized_vol_bp(mid_hist, window=120)
        prev_mid, prev_spread_bp = book.mid, book.spread_bp
        trades = []
        if "trade_px" in df.columns and np.isfinite(row.get("trade_px", np.nan)):
            trades.append({"price": float(row["trade_px"]), "size": float(row.get("trade_sz",0.0)),
                           "aggressor": int(row.get("aggressor",0)), "ts_ns": ts_ns})

        feats = compute_features(None, book, trades, state).astype("float32")

        try:
            payload = {"symbol": symbol.split(".")[0], "features": feats.tolist(), "ts": ts_ns}
            if HMM_TAG: payload["tag"] = HMM_TAG
            r = client.post("/infer", json=payload).json()
            m_state, probs, conf = int(r["state"]), r["probs"], float(r["confidence"])
        except Exception:
            m_state, probs, conf = 0, [1.0], 1.0

        states_log.append({"ts_ns": ts_ns, "state": m_state, "conf": conf})
        side, qty, limit_px = decide_action(m_state, conf, feats, scfg)

        block = check_gates(
            context=type("C", (), {"cfg": scfg, "trading_enabled": True, "instrument_id": symbol, "last_flip_ns": 0})(),
            now_ns=ts_ns,
            spread_bp=book.spread_bp,
            qty=qty,
            portfolio=type("P", (), {"net_position": lambda _id: qty_pos})(),
            metrics=type("M", (), {})(),
        )
        if block is not Block.OK or side == "HOLD" or not np.isfinite(book.mid):
            blocks_log.append({"ts_ns": ts_ns, "reason": block.value if block else "HOLD"})
            continue

        if side == "BUY":
            l1_depth = book.ask_sz if book.ask_sz else qty
            px = fill_price(side, book.mid, book.bid, book.ask, book.spread_bp, vol_bp, qty, l1_depth, mid_hist)
            qty_pos += qty; cash -= qty * px; last_px = px
            trades_log.append({"ts_ns": ts_ns, "side":"BUY", "qty":qty, "price":px, "vol_bp":vol_bp,
                             "spread_bp":book.spread_bp, "l1_depth":l1_depth})
        elif side == "SELL":
            l1_depth = book.bid_sz if book.bid_sz else qty
            px = fill_price(side, book.mid, book.bid, book.ask, book.spread_bp, vol_bp, qty, l1_depth, mid_hist)
            qty_pos -= qty; cash += qty * px; last_px = px
            trades_log.append({"ts_ns": ts_ns, "side":"SELL","qty":qty,"price":px,"vol_bp":vol_bp,
                             "spread_bp":book.spread_bp, "l1_depth":l1_depth})
        fee = abs(qty * (book.mid if np.isfinite(book.mid) else last_px)) * (fees_bps/1e4)
        cash -= fee

    mtm_px = df["ask_px"].combine(df["bid_px"], np.nanmean).iloc[-1]
    if not np.isfinite(mtm_px): mtm_px = last_px if np.isfinite(last_px) else np.nan
    pnl = cash + qty_pos * (mtm_px if np.isfinite(mtm_px) else 0.0)

    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(trades_log).to_csv(out_dir / "trades.csv", index=False)
    pd.DataFrame(states_log).to_csv(out_dir / "state_timeline.csv", index=False)
    pd.DataFrame(blocks_log).to_csv(out_dir / "guardrails.csv", index=False)
    pd.DataFrame(dq_log).to_csv(out_dir / "data_quality_issues.csv", index=False)
    print(f"[M4-fallback] Done. PnL={pnl:.4f}. Artifacts in {out_dir}")

def nautilus_engine(cfg: dict, out_dir: Path):
    try:
        # Depending on Nautilus version, more setup is required here.
        print("[M4] Nautilus BacktestEngine path is not implemented in this scaffold.")
        minimal_engine(cfg, out_dir)
    except Exception as e:
        print(f"[M4] Engine path failed ({e}); using minimal simulator.")
        minimal_engine(cfg, out_dir)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = load_config(args.config)
    out_dir = Path("data/processed")
    if USE_NAUTILUS:
        nautilus_engine(cfg, out_dir)
    else:
        minimal_engine(cfg, out_dir)

if __name__ == "__main__":
    main()
