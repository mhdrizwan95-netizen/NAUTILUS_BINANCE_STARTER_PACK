"""Grid search framework for parameter optimization."""

import itertools
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from .config import settings
from .engine import BacktestEngine


@dataclass
class GridSearchResult:
    """Result of a single grid search run."""
    params: dict[str, Any]
    metrics: dict[str, float]
    run_id: str


@dataclass
class GridSearchSummary:
    """Summary of grid search results."""
    best_result: GridSearchResult | None = None
    all_results: list[GridSearchResult] = field(default_factory=list)
    param_grid: dict[str, list] = field(default_factory=dict)
    strategy: str = ""
    symbol: str = ""
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "symbol": self.symbol,
            "param_grid": self.param_grid,
            "total_runs": len(self.all_results),
            "best_params": self.best_result.params if self.best_result else None,
            "best_metrics": self.best_result.metrics if self.best_result else None,
            "best_run_id": self.best_result.run_id if self.best_result else None,
        }


class GridSearch:
    """Grid search for strategy parameter optimization.
    
    Runs backtests across all combinations of parameter values
    and identifies the best-performing configuration.
    """
    
    def __init__(
        self,
        strategy: str = "momentum",
        symbols: list[str] | None = None,
        initial_equity: float = 10000.0,
        metric: str = "sharpe_ratio",
    ):
        """Initialize grid search.
        
        Args:
            strategy: Strategy type ("momentum" or "trend_follow")
            symbols: Symbols to backtest
            initial_equity: Starting equity
            metric: Metric to optimize ("sharpe_ratio", "total_return", etc.)
        """
        self.strategy = strategy
        self.symbols = symbols
        self.initial_equity = initial_equity
        self.metric = metric
        self.results: list[GridSearchResult] = []
    
    def search(
        self,
        param_grid: dict[str, list],
        max_runs: int | None = None,
    ) -> GridSearchSummary:
        """Run grid search over parameter combinations.
        
        Args:
            param_grid: Dict of parameter names to list of values
            max_runs: Optional limit on number of runs
            
        Returns:
            GridSearchSummary with results
        """
        # Generate all combinations
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        combinations = list(itertools.product(*param_values))
        
        if max_runs and len(combinations) > max_runs:
            logger.warning(
                f"Grid has {len(combinations)} combinations, limiting to {max_runs}"
            )
            combinations = combinations[:max_runs]
        
        logger.info(f"Starting grid search with {len(combinations)} parameter combinations")
        
        self.results = []
        best_result = None
        best_metric_value = float("-inf")
        
        for i, combo in enumerate(combinations):
            params = dict(zip(param_names, combo))
            logger.info(f"[{i+1}/{len(combinations)}] Testing params: {params}")
            
            try:
                result = self._run_single(params)
                self.results.append(result)
                
                metric_value = result.metrics.get(self.metric, float("-inf"))
                if metric_value > best_metric_value:
                    best_metric_value = metric_value
                    best_result = result
                    logger.info(f"  New best {self.metric}: {metric_value:.4f}")
                    
            except Exception as e:
                logger.error(f"  Failed: {e}")
        
        summary = GridSearchSummary(
            best_result=best_result,
            all_results=self.results,
            param_grid=param_grid,
            strategy=self.strategy,
            symbol=",".join(self.symbols) if self.symbols else "all",
        )
        
        # Save summary
        self._save_summary(summary)
        
        return summary
    
    def _run_single(self, params: dict[str, Any]) -> GridSearchResult:
        """Run a single backtest with given parameters."""
        engine = BacktestEngine(
            symbols=self.symbols,
            strategy=self.strategy,
            initial_equity=self.initial_equity,
        )
        
        # Apply parameters to strategy
        if hasattr(engine.strategy, "__dict__"):
            for key, value in params.items():
                if hasattr(engine.strategy, key):
                    setattr(engine.strategy, key, value)
        
        # Run backtest
        result = engine.run()
        
        return GridSearchResult(
            params=params,
            metrics=result.get("metrics", {}),
            run_id=result.get("run_id", "unknown"),
        )
    
    def _save_summary(self, summary: GridSearchSummary) -> None:
        """Save grid search summary to file."""
        output_dir = Path(settings.RESULTS_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        summary_file = output_dir / f"grid_search_{summary.strategy}.json"
        with open(summary_file, "w") as f:
            json.dump(summary.to_dict(), f, indent=2)
        
        logger.info(f"Grid search results saved to: {summary_file}")


def run_momentum_grid_search() -> GridSearchSummary:
    """Run grid search for momentum strategy."""
    param_grid = {
        "lookback": [10, 20, 30],
        "momentum_threshold": [0.01, 0.02, 0.03],
        "volume_ratio": [1.2, 1.5, 2.0],
        "stop_loss_pct": [0.015, 0.02, 0.025],
    }
    
    gs = GridSearch(strategy="momentum", metric="sharpe_ratio")
    return gs.search(param_grid)


def run_trend_grid_search() -> GridSearchSummary:
    """Run grid search for trend follow strategy."""
    param_grid = {
        "fast_period": [5, 10, 15],
        "slow_period": [20, 30, 40],
        "atr_stop_mult": [1.5, 2.0, 2.5],
        "min_trend_strength": [0.0005, 0.001, 0.002],
    }
    
    gs = GridSearch(strategy="trend_follow", metric="sharpe_ratio")
    return gs.search(param_grid)
