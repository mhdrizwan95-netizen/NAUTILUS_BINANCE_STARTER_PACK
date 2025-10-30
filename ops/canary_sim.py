import os, json, subprocess, tempfile, shutil
from pathlib import Path

import yaml

# Helper bridges to the lightweight CSV scorer (`scripts/backtest_hmm.py`).

def run_backtest_with_tag(tag: str, config: str) -> dict:
    env = os.environ.copy()
    env["HMM_TAG"] = tag
    with open(config, "r") as fh:
        cfg = yaml.safe_load(fh)

    csv_path = Path(env.get("CANARY_BACKTEST_CSV", cfg.get("data_csv", "")))
    if not csv_path:
        raise RuntimeError("Set CANARY_BACKTEST_CSV or add data_csv to the config for canary checks")
    if not csv_path.exists():
        raise FileNotFoundError(f"Canary backtest CSV not found: {csv_path}")

    symbol = env.get("CANARY_SYMBOL") or (cfg.get("symbols") or ["BTCUSDT"])[0].split(".")[0]
    model_path = env.get("CANARY_MODEL", "engine/models/hmm_policy.pkl")
    quote = env.get("CANARY_QUOTE", "100")

    out_file = Path(tempfile.gettempdir()) / f"canary_{tag}.json"
    cmd = [
        "python",
        "scripts/backtest_hmm.py",
        "--csv",
        str(csv_path),
        "--model",
        model_path,
        "--symbol",
        symbol,
        "--quote",
        str(quote),
        "--out",
        str(out_file),
    ]

    out = subprocess.run(cmd, env=env, capture_output=True, text=True)
    # Load artifacts to summarize
    data_dir = Path("data/processed")
    # TODO: parse generated KPIs once the new pipeline is wired into dashboards.
    payload = {
        "ok": out.returncode == 0,
        "stdout": out.stdout[-4000:],
        "stderr": out.stderr[-4000:],
    }
    if out_file.exists():
        payload["summary_path"] = str(out_file)
    return payload

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--config", default="backtests/configs/crypto_spot.yaml")
    args = ap.parse_args()
    res = run_backtest_with_tag(args.tag, args.config)
    print(json.dumps(res, indent=2))
