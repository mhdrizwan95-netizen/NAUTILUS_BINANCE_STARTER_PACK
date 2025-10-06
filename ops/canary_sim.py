import os, json, subprocess, tempfile, shutil
from pathlib import Path

# You can keep your run_backtest.py as-is; it calls /infer without tag.
# We'll override by setting ENV HMM_TAG, and modify run_backtest.py (tiny patch) to include tag if set.

def run_backtest_with_tag(tag: str, config: str) -> dict:
    env = os.environ.copy()
    env["HMM_TAG"] = tag
    # Run your backtest; it should read HMM_TAG and pass {"tag": os.getenv("HMM_TAG")} to /infer
    out = subprocess.run(
        ["python", "backtests/run_backtest.py", "--config", config],
        env=env, capture_output=True, text=True
    )
    # Load artifacts to summarize
    data_dir = Path("data/processed")
    trades = (data_dir / "trades.csv").read_text() if (data_dir / "trades.csv").exists() else ""
    guards = (data_dir / "guardrails.csv").read_text() if (data_dir / "guardrails.csv").exists() else ""
    # TODO: parse CSVs to compute KPIs; placeholder summary:
    return {"ok": out.returncode == 0, "stdout": out.stdout[-4000:], "stderr": out.stderr[-4000:]}

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--config", default="backtests/configs/crypto_spot.yaml")
    args = ap.parse_args()
    res = run_backtest_with_tag(args.tag, args.config)
    print(json.dumps(res, indent=2))
