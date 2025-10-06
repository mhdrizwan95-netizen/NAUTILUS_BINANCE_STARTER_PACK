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
    use_h2 = cfg.get("use_h2", False)
    mid_hist: list[float] = []
    prev_ts_ns = None
    prev_mid = None
    prev_spread_bp = None
    dq_log = []
    mm = MM() if use_h2 else None  # macroscopic feature accumulator
    # MM class defined below for simplicity
    class MM:
        def __init__(self, maxlen=600):
            from collections import deque
            import numpy as np
            self.mids = deque(maxlen=maxlen)
            self.spreads_bp = deque(maxlen=maxlen)
            self.vol_bp = deque(maxlen=maxlen)
        def update(self, mid: float, spread_bp: float):
            self.mids.append(mid)
            self.spreads_bp.append(spread_bp)
            if len(self.mids) > 2:
                arr = np.asarray(self.mids, dtype=np.float64)
                rets = np.diff(arr) / np.maximum(arr[:-1], 1e-9)
                vol_bp = float(np.std(rets[-120:]) * 1e4 if len(rets) >= 2 else 0.0)
            else:
                vol_bp = 0.0
            self.vol_bp.append(vol_bp)
        def macro_feats(self):
            if len(self.mids) < 30:
                return np.zeros(6, dtype=np.float32)
            mids = np.asarray(self.mids[-300:], dtype=np.float64)
            x = np.arange(len(mids))
            slope = float(np.polyfit(x, mids, 1)[0]) / max(np.mean(mids), 1e-9)
            vol = float(np.median(self.vol_bp[-300:]) if self.vol_bp else 0.0)
            spr = float(np.median(self.spreads_bp[-300:]) if self.spreads_bp else 0.0)
            vol_q = float(np.quantile(self.vol_bp[-300:], 0.75) if len(self.vol_bp) > 10 else 0.0)
            spr_q = float(np.quantile(self.spreads_bp[-300:], 0.75) if len(self.spreads_bp) > 10 else 0.0)
            trend = float(np.sign(slope))
            return np.array([vol, vol_q, spr, spr_q, slope, trend], dtype=np.float32)

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

        # H2 path if enabled
        macro_state = 1  # default neutral
        if use_h2 and mm:
            mm.update(book.mid, book.spread_bp)
            macro_vec = mm.macro_feats().tolist()
            try:
                payload = {"symbol": symbol.split(".")[0], "macro_feats": macro_vec, "micro_feats": feats.tolist(), "ts": ts_ns}
                if HMM_TAG: payload["tag"] = HMM_TAG
                r = client.post("/infer_h2", json=payload).json()
                macro_state, m_state, conf = int(r["macro_state"]), int(r["micro_state"]), float(r["confidence"])
            except Exception:
                m_state, conf = 0, 1.0
        else:
            try:
                payload = {"symbol": symbol.split(".")[0], "features": feats.tolist(), "ts": ts_ns}
                if HMM_TAG: payload["tag"] = HMM_TAG
                r = client.post("/infer", json=payload).json()
                m_state, probs, conf = int(r["state"]), r["probs"], float(r["confidence"])
            except Exception:
                m_state, probs, conf = 0, [1.0], 1.0

        states_log.append({"ts_ns": ts_ns, "state": m_state, "macro_state": macro_state, "conf": conf})
        side, qty, limit_px = decide_action(m_state, conf, feats, scfg)
        # macro-aware guardrails: shrink risk in risk-off
        risk_bias = {0:0.5, 1:1.0, 2:1.5}.get(macro_state, 1.0)
        qty *= risk_bias

        # M14: log correlation metrics
        if mm and corr_tracker.is_ready() and corr_tracker.is_ready():
            corr = corr_tracker.get_pairwise_correlation(sym_base, "ETH" if "BTC" in sym_base else "BTC")
            states_log[-1].update({
                "corr_btc_eth": float(corr) if corr else 0.0,
                "port_vol": float(0.0),  # Placeholder - needs portfolio calculation
                "corr_regime": "normal"  # Placeholder - needs correlation regime calculation
            })

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
