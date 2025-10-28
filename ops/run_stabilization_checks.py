from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from contextlib import suppress
from datetime import datetime
from typing import Dict, Tuple

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from prometheus_client.parser import text_string_to_metric_families

from engine.runtime.config import RuntimeConfig, load_runtime_config
from engine.metrics import generate_latest
from tools.synthetic_feed import run_synthetic_runtime

try:
    import yaml
except ImportError:
    yaml = None


def _build_harness_namespace(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        config=args.config,
        symbols_per_strategy=args.symbols_per_strategy,
        refresh_seconds=args.refresh_seconds,
        signal_interval=args.signal_interval,
        burst=args.burst,
        starting_cash=args.starting_cash,
        base_price=args.base_price,
        spike_chance=args.spike_chance,
    )


async def _run_harness(args: argparse.Namespace) -> None:
    harness_args = _build_harness_namespace(args)
    task = asyncio.create_task(run_synthetic_runtime(harness_args))
    try:
        await asyncio.wait_for(task, timeout=args.duration_seconds)
    except asyncio.TimeoutError:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def _collect_metrics() -> Dict[str, Tuple]:
    raw = generate_latest().decode()
    families: Dict[str, Tuple] = {}
    for fam in text_string_to_metric_families(raw):
        families[fam.name] = fam
    return families


def _sum_counter(families: Dict[str, Tuple], name: str) -> float:
    family = families.get(name)
    if not family:
        return 0.0
    return sum(sample.value for sample in family.samples if sample.name == name)


def _histogram_quantiles(families: Dict[str, Tuple], name: str, quantiles: Tuple[float, ...]) -> Dict[str, Dict[float, float]]:
    family = families.get(name)
    results: Dict[str, Dict[float, float]] = defaultdict(dict)
    if not family:
        return results
    buckets: Dict[str, Dict[float, float]] = defaultdict(dict)
    totals: Dict[str, float] = {}
    for sample in family.samples:
        if sample.name.endswith("_bucket"):
            strategy = sample.labels.get("strategy", "all")
            edge = float(sample.labels["le"])
            buckets[strategy][edge] = sample.value
        elif sample.name.endswith("_count"):
            strategy = sample.labels.get("strategy", "all")
            totals[strategy] = sample.value
    for strategy, bucket_counts in buckets.items():
        total = totals.get(strategy, 0.0)
        if total <= 0:
            continue
        ordered = sorted(bucket_counts.items(), key=lambda kv: kv[0])
        for q in quantiles:
            target = q * total
            cumulative = 0.0
            threshold = ordered[-1][0]
            for edge, count in ordered:
                cumulative = count
                if cumulative >= target:
                    threshold = edge
                    break
            results[strategy][q] = threshold
    return results


def _gauge_values(families: Dict[str, Tuple], name: str, label_key: str) -> Dict[str, float]:
    family = families.get(name)
    values: Dict[str, float] = {}
    if not family:
        return values
    for sample in family.samples:
        if sample.name == name:
            label = sample.labels.get(label_key, "unknown")
            values[label] = sample.value
    return values


def _evaluate_metrics(args: argparse.Namespace, cfg: RuntimeConfig, families: Dict[str, Tuple]) -> int:
    failures = 0
    mismatch_total = _sum_counter(families, "strategy_leverage_mismatch_total")
    if mismatch_total > args.allowed_leverage_mismatches:
        print(f"[FAIL] Leverage mismatches detected: {mismatch_total}")
        failures += 1
    else:
        print(f"[PASS] Leverage mismatches within limits ({mismatch_total})")

    quantile_data = _histogram_quantiles(
        families,
        "strategy_signal_latency_seconds_bucket",
        (0.5, 0.95),
    )
    worst_p50 = 0.0
    worst_p95 = 0.0
    for strategy, quantiles in quantile_data.items():
        p50 = quantiles.get(0.5, 0.0)
        p95 = quantiles.get(0.95, 0.0)
        worst_p50 = max(worst_p50, p50)
        worst_p95 = max(worst_p95, p95)
        print(f"[INFO] Latency quantiles for {strategy}: p50={p50:.4f}s p95={p95:.4f}s")
    if worst_p50 > args.max_latency_p50 or worst_p95 > args.max_latency_p95:
        print(f"[FAIL] Latency thresholds exceeded (p50={worst_p50:.4f}s, p95={worst_p95:.4f}s)")
        failures += 1
    else:
        print(f"[PASS] Latency within thresholds (p50={worst_p50:.4f}s, p95={worst_p95:.4f}s)")

    submitted = _sum_counter(families, "orders_submitted_total")
    rejected = _sum_counter(families, "orders_rejected_total")
    failure_rate = (rejected / submitted) if submitted else 0.0
    if failure_rate > args.max_failure_rate:
        print(f"[FAIL] Order failure rate {failure_rate:.4%} exceeds {args.max_failure_rate:.2%}")
        failures += 1
    else:
        print(f"[PASS] Order failure rate {failure_rate:.4%} within limit")

    bucket_usage = _gauge_values(families, "strategy_bucket_usage_fraction", "bucket")
    tolerance = args.bucket_headroom
    for bucket, usage in bucket_usage.items():
        budget = getattr(cfg.buckets, bucket, None)
        if budget is None:
            continue
        if usage > (budget + tolerance):
            print(f"[FAIL] Bucket '{bucket}' usage {usage:.4f} exceeds budget {budget:.4f} + headroom {tolerance:.4f}")
            failures += 1
        else:
            print(f"[PASS] Bucket '{bucket}' usage {usage:.4f} within budget {budget:.4f}")

    return failures


def _load_thresholds_file(thresholds_file: str) -> dict:
    """Load thresholds from YAML file, return empty dict if not available."""
    if yaml is None:
        print("[WARN] PyYAML not available, cannot load thresholds file")
        return {}
    try:
        with open(thresholds_file, 'r') as f:
            thresholds = yaml.safe_load(f)
            print(f"[INFO] Loaded thresholds from {thresholds_file}: {thresholds}")
            return thresholds or {}
    except Exception as e:
        print(f"[WARN] Failed to load thresholds from {thresholds_file}: {e}")
        return {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run synthetic harness and evaluate stabilization checks.")
    parser.add_argument("--config", default="config/runtime.yaml")
    parser.add_argument("--duration-seconds", type=float, default=30.0)
    parser.add_argument("--symbols-per-strategy", type=int, default=40)
    parser.add_argument("--refresh-seconds", type=float, default=10.0)
    parser.add_argument("--signal-interval", type=float, default=0.5)
    parser.add_argument("--burst", type=int, default=6)
    parser.add_argument("--starting-cash", type=float, default=100_000.0)
    parser.add_argument("--base-price", type=float, default=100.0)
    parser.add_argument("--spike-chance", type=float, default=0.02)
    parser.add_argument("--allowed-leverage-mismatches", type=int, default=0)
    parser.add_argument("--max-latency-p50", type=float, default=0.150)
    parser.add_argument("--max-latency-p95", type=float, default=0.400)
    parser.add_argument("--max-failure-rate", type=float, default=0.005)
    parser.add_argument("--bucket-headroom", type=float, default=0.02)
    parser.add_argument("--thresholds", default=None, help="YAML file with default thresholds")
    return parser.parse_args()


def _apply_threshold_defaults(args: argparse.Namespace) -> argparse.Namespace:
    """Apply defaults from thresholds file to argparse namespace."""
    if args.thresholds:
        thresholds = _load_thresholds_file(args.thresholds)
        # Apply YAML values as defaults, but CLI args take precedence
        for key, value in thresholds.items():
            attr_name = key.replace('-', '_')
            if hasattr(args, attr_name):
                # CLI args override YAML defaults (CLI will have non-default values)
                current_value = getattr(args, attr_name)
                # Simple heuristic: if value matches parser default, apply YAML default
                parser = argparse.ArgumentParser()
                parser.add_argument(f"--{key}", dest=attr_name)
                test_args, _ = parser.parse_known_args([])
                default_value = getattr(test_args, attr_name)
                if current_value == default_value:
                    setattr(args, attr_name, value)
                    print(f"[INFO] Using YAML threshold {key}={value}")
    return args


def _generate_report(args: argparse.Namespace, cfg: RuntimeConfig, families: Dict[str, Tuple], failures: int) -> dict:
    """Generate JSON report with stabilization results."""
    timestamp = datetime.utcnow().isoformat()
    mismatch_total = _sum_counter(families, "strategy_leverage_mismatch_total")
    quantile_data = _histogram_quantiles(
        families,
        "strategy_signal_latency_seconds_bucket",
        (0.5, 0.95),
    )
    submitted = _sum_counter(families, "orders_submitted_total")
    rejected = _sum_counter(families, "orders_rejected_total")
    failure_rate = (rejected / submitted) if submitted else 0.0
    bucket_usage = _gauge_values(families, "strategy_bucket_usage_fraction", "bucket")

    # Calculate worst latencies
    worst_p50 = max((quantiles.get(0.5, 0.0) for quantiles in quantile_data.values()), default=0.0)
    worst_p95 = max((quantiles.get(0.95, 0.0) for quantiles in quantile_data.values()), default=0.0)

    return {
        "timestamp": timestamp,
        "config": args.config,
        "duration_seconds": args.duration_seconds,
        "symbols_per_strategy": args.symbols_per_strategy,
        "results": {
            "leverage_mismatches": int(mismatch_total),
            "max_allowed_mismatches": args.allowed_leverage_mismatches,
            "latency_max_p50": round(worst_p50, 4),
            "latency_max_p95": round(worst_p95, 4),
            "latency_threshold_p50": args.max_latency_p50,
            "latency_threshold_p95": args.max_latency_p95,
            "order_failure_rate": round(failure_rate, 6),
            "max_failure_rate": args.max_failure_rate,
            "bucket_usage": {k: round(v, 4) for k, v in bucket_usage.items()},
            "bucket_headroom": args.bucket_headroom,
            "config_budgets": {k: getattr(cfg.buckets, k, None) for k in bucket_usage.keys()},
        },
        "passed": failures == 0,
        "failure_count": failures,
    }


def _save_report(report: dict) -> None:
    """Save report to ops/reports/ directory."""
    timestamp = datetime.fromisoformat(report["timestamp"]).strftime("%Y%m%d_%H%M%S")
    filename = f"ops/reports/stabilization_{timestamp}.json"
    with open(filename, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"[INFO] Report saved to {filename}")


def main() -> None:
    args = parse_args()
    args = _apply_threshold_defaults(args)
    asyncio.run(_run_harness(args))
    cfg = load_runtime_config(args.config)
    families = _collect_metrics()
    failures = _evaluate_metrics(args, cfg, families)
    report = _generate_report(args, cfg, families, failures)
    _save_report(report)
    if failures:
        print(f"[SUMMARY] Stabilization check failed ({failures} issue(s) detected).")
        sys.exit(1)
    print("[SUMMARY] All stabilization checks passed.")


if __name__ == "__main__":
    main()
