"""CLI entry point for the backtest suite."""

import argparse
import json
import sys
from pathlib import Path

from loguru import logger

from .config import settings
from .engine import BacktestEngine


def setup_logging() -> None:
    """Configure logging."""
    logger.remove()
    logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )


def cmd_backtest(args) -> int:
    """Run a single backtest."""
    symbols = None
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    
    if args.data_dir:
        settings.HISTORICAL_DIR = args.data_dir
    if args.output_dir:
        settings.RESULTS_DIR = args.output_dir
    if args.cost_bps is not None:
        settings.COST_BPS = args.cost_bps
    
    Path(settings.RESULTS_DIR).mkdir(parents=True, exist_ok=True)
    
    logger.info("=" * 60)
    logger.info("Nautilus Backtest Suite")
    logger.info("=" * 60)
    logger.info(f"Strategy: {args.strategy}")
    logger.info(f"Symbols: {symbols or 'all available'}")
    logger.info(f"Initial equity: ${args.initial_equity:,.2f}")
    
    if args.dry_run:
        logger.info("Dry run mode - validating configuration...")
        engine = BacktestEngine(symbols=symbols, strategy=args.strategy, initial_equity=args.initial_equity)
        bars = engine.load_data()
        return 0 if bars > 0 else 1
    
    try:
        engine = BacktestEngine(symbols=symbols, strategy=args.strategy, initial_equity=args.initial_equity)
        results = engine.run()
        
        if "error" in results:
            logger.error(f"Backtest failed: {results['error']}")
            return 1
        
        metrics = results.get("metrics", {})
        logger.info("=" * 60)
        logger.info("BACKTEST RESULTS")
        logger.info("=" * 60)
        logger.info(f"Sharpe: {metrics.get('sharpe_ratio', 0):.3f} | Return: {metrics.get('total_return', 0):.2%} | Win Rate: {metrics.get('win_rate', 0):.2%}")
        logger.info(f"Max DD: {metrics.get('max_drawdown', 0):.2%} | Trades: {metrics.get('total_trades', 0)} | Final: ${metrics.get('final_equity', 0):,.2f}")
        
        results_file = f"{settings.RESULTS_DIR}/{results['run_id']}_results.json"
        with open(results_file, "w") as f:
            json.dump(results, f, indent=2)
        logger.info(f"Results saved: {results_file}")
        return 0
        
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        logger.exception(f"Backtest failed: {e}")
        return 1


def cmd_grid_search(args) -> int:
    """Run grid search optimization."""
    from .grid_search import GridSearch
    
    logger.info("=" * 60)
    logger.info("Grid Search Optimization")
    logger.info("=" * 60)
    logger.info(f"Strategy: {args.strategy}")
    logger.info(f"Metric: {args.metric}")
    logger.info(f"Max runs: {args.max_runs or 'unlimited'}")
    
    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else None
    
    gs = GridSearch(
        strategy=args.strategy,
        symbols=symbols,
        initial_equity=args.initial_equity,
        metric=args.metric,
    )
    
    # Define parameter grids
    if args.strategy == "momentum":
        param_grid = {
            "lookback": [10, 20, 30],
            "momentum_threshold": [0.01, 0.02, 0.03],
            "volume_ratio": [1.2, 1.5, 2.0],
        }
    else:  # trend_follow
        param_grid = {
            "fast_period": [5, 10, 15],
            "slow_period": [20, 30, 40],
            "atr_stop_mult": [1.5, 2.0, 2.5],
        }
    
    summary = gs.search(param_grid, max_runs=args.max_runs)
    
    if summary.best_result:
        logger.info("=" * 60)
        logger.info("BEST RESULT")
        logger.info("=" * 60)
        logger.info(f"Params: {summary.best_result.params}")
        logger.info(f"{args.metric}: {summary.best_result.metrics.get(args.metric, 0):.4f}")
    
    return 0


def cmd_generate_presets(args) -> int:
    """Generate presets from grid search results."""
    from .grid_search import GridSearch
    from .preset_generator import PresetGenerator
    
    logger.info("=" * 60)
    logger.info("Preset Generation")
    logger.info("=" * 60)
    
    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else None
    
    # Run grid search first
    gs = GridSearch(strategy=args.strategy, symbols=symbols, initial_equity=args.initial_equity)
    
    if args.strategy == "momentum":
        param_grid = {"lookback": [15, 20, 25], "momentum_threshold": [0.015, 0.02, 0.025]}
    else:
        param_grid = {"fast_period": [8, 10, 12], "slow_period": [25, 30, 35]}
    
    summary = gs.search(param_grid)
    
    # Generate presets
    generator = PresetGenerator(
        min_sharpe=args.min_sharpe,
        min_win_rate=args.min_win_rate,
        max_drawdown=args.max_drawdown,
    )
    
    candidates = generator.generate_from_grid_search(summary, top_n=args.top_n)
    
    if not candidates:
        logger.warning("No candidates met the quality thresholds")
        return 1
    
    # Register presets
    if not args.dry_run:
        results = generator.register_presets(candidates)
        logger.info(f"Registered {len([r for r in results if r.get('status') == 'registered'])} presets")
    else:
        logger.info(f"[DRY RUN] Would register {len(candidates)} presets")
        for c in candidates:
            logger.info(f"  - {c.preset_id}: {c.params}")
    
    generator.save_candidates(candidates)
    return 0


def main() -> int:
    """Main entry point."""
    setup_logging()
    
    parser = argparse.ArgumentParser(description="Nautilus Backtest Suite")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Backtest command
    bt_parser = subparsers.add_parser("backtest", help="Run a single backtest")
    bt_parser.add_argument("--strategy", type=str, default="momentum", choices=["momentum", "trend_follow"])
    bt_parser.add_argument("--symbols", type=str, default=None)
    bt_parser.add_argument("--initial-equity", type=float, default=10000.0)
    bt_parser.add_argument("--data-dir", type=str, default=None)
    bt_parser.add_argument("--output-dir", type=str, default=None)
    bt_parser.add_argument("--cost-bps", type=float, default=None)
    bt_parser.add_argument("--dry-run", action="store_true")
    bt_parser.set_defaults(func=cmd_backtest)
    
    # Grid search command
    gs_parser = subparsers.add_parser("grid-search", help="Run parameter optimization")
    gs_parser.add_argument("--strategy", type=str, default="momentum", choices=["momentum", "trend_follow"])
    gs_parser.add_argument("--symbols", type=str, default=None)
    gs_parser.add_argument("--initial-equity", type=float, default=10000.0)
    gs_parser.add_argument("--metric", type=str, default="sharpe_ratio")
    gs_parser.add_argument("--max-runs", type=int, default=None)
    gs_parser.set_defaults(func=cmd_grid_search)
    
    # Preset generation command
    pg_parser = subparsers.add_parser("generate-presets", help="Generate presets from optimization")
    pg_parser.add_argument("--strategy", type=str, default="momentum", choices=["momentum", "trend_follow"])
    pg_parser.add_argument("--symbols", type=str, default=None)
    pg_parser.add_argument("--initial-equity", type=float, default=10000.0)
    pg_parser.add_argument("--min-sharpe", type=float, default=0.5)
    pg_parser.add_argument("--min-win-rate", type=float, default=0.45)
    pg_parser.add_argument("--max-drawdown", type=float, default=0.15)
    pg_parser.add_argument("--top-n", type=int, default=3)
    pg_parser.add_argument("--dry-run", action="store_true")
    pg_parser.set_defaults(func=cmd_generate_presets)
    
    args = parser.parse_args()
    
    if not args.command:
        # Default to backtest for backward compatibility
        args.strategy = "momentum"
        args.symbols = None
        args.initial_equity = 10000.0
        args.data_dir = None
        args.output_dir = None
        args.cost_bps = None
        args.dry_run = False
        return cmd_backtest(args)
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

