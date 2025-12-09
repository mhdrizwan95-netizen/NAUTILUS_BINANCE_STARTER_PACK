"""Automated preset generation from backtest results."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from .config import settings
from .grid_search import GridSearchSummary


@dataclass
class PresetCandidate:
    """Candidate preset from backtest results."""
    strategy: str
    symbol: str
    preset_id: str
    params: dict[str, Any]
    metrics: dict[str, float]
    confidence: float


class PresetGenerator:
    """Generates and registers presets from backtest results.
    
    Analyzes grid search or individual backtest results to identify
    parameter configurations worth registering as presets.
    """
    
    def __init__(
        self,
        param_controller_url: str | None = None,
        min_sharpe: float = 0.5,
        min_win_rate: float = 0.45,
        max_drawdown: float = 0.15,
    ):
        """Initialize preset generator.
        
        Args:
            param_controller_url: URL of param controller service
            min_sharpe: Minimum Sharpe ratio for preset consideration
            min_win_rate: Minimum win rate
            max_drawdown: Maximum allowed drawdown
        """
        self.param_controller_url = param_controller_url or settings.PARAM_CONTROLLER
        self.min_sharpe = min_sharpe
        self.min_win_rate = min_win_rate
        self.max_drawdown = max_drawdown
    
    def generate_from_grid_search(
        self,
        summary: GridSearchSummary,
        top_n: int = 3,
    ) -> list[PresetCandidate]:
        """Generate preset candidates from grid search results.
        
        Args:
            summary: Grid search summary
            top_n: Number of top presets to generate
            
        Returns:
            List of preset candidates
        """
        candidates = []
        
        # Sort results by Sharpe ratio
        sorted_results = sorted(
            summary.all_results,
            key=lambda r: r.metrics.get("sharpe_ratio", float("-inf")),
            reverse=True,
        )
        
        for i, result in enumerate(sorted_results[:top_n]):
            metrics = result.metrics
            
            # Check quality thresholds
            sharpe = metrics.get("sharpe_ratio", 0)
            win_rate = metrics.get("win_rate", 0)
            max_dd = metrics.get("max_drawdown", 1)
            
            if sharpe < self.min_sharpe:
                logger.info(f"Skipping result {i+1}: Sharpe {sharpe:.3f} < {self.min_sharpe}")
                continue
            
            if win_rate < self.min_win_rate:
                logger.info(f"Skipping result {i+1}: Win rate {win_rate:.2%} < {self.min_win_rate:.2%}")
                continue
            
            if max_dd > self.max_drawdown:
                logger.info(f"Skipping result {i+1}: Drawdown {max_dd:.2%} > {self.max_drawdown:.2%}")
                continue
            
            # Generate preset ID
            preset_id = self._generate_preset_id(summary.strategy, i + 1, metrics)
            
            # Calculate confidence score
            confidence = self._calculate_confidence(metrics)
            
            candidates.append(PresetCandidate(
                strategy=summary.strategy,
                symbol=summary.symbol,
                preset_id=preset_id,
                params=result.params,
                metrics=dict(metrics),
                confidence=confidence,
            ))
        
        logger.info(f"Generated {len(candidates)} preset candidates from grid search")
        return candidates
    
    def register_presets(
        self,
        candidates: list[PresetCandidate],
        dry_run: bool = False,
    ) -> list[dict]:
        """Register preset candidates with param controller.
        
        Args:
            candidates: List of preset candidates
            dry_run: If True, don't actually register
            
        Returns:
            List of registration results
        """
        results = []
        
        for candidate in candidates:
            if dry_run:
                logger.info(f"[DRY RUN] Would register: {candidate.preset_id}")
                results.append({
                    "preset_id": candidate.preset_id,
                    "status": "dry_run",
                })
                continue
            
            try:
                # Parse symbol(s)
                symbols = candidate.symbol.split(",") if candidate.symbol else ["BTCUSDT"]
                
                for symbol in symbols:
                    symbol = symbol.strip()
                    if not symbol or symbol == "all":
                        symbol = "BTCUSDT"  # Default
                    
                    response = httpx.post(
                        f"{self.param_controller_url}/preset/register/{candidate.strategy}/{symbol}",
                        json={
                            "preset_id": candidate.preset_id,
                            "params": candidate.params,
                        },
                        timeout=10.0,
                    )
                    
                    if response.status_code == 200:
                        logger.info(f"Registered preset: {candidate.preset_id} for {symbol}")
                        results.append({
                            "preset_id": candidate.preset_id,
                            "symbol": symbol,
                            "status": "registered",
                        })
                    else:
                        logger.warning(f"Failed to register {candidate.preset_id}: {response.text}")
                        results.append({
                            "preset_id": candidate.preset_id,
                            "symbol": symbol,
                            "status": "failed",
                            "error": response.text,
                        })
                        
            except Exception as e:
                logger.error(f"Error registering {candidate.preset_id}: {e}")
                results.append({
                    "preset_id": candidate.preset_id,
                    "status": "error",
                    "error": str(e),
                })
        
        return results
    
    def _generate_preset_id(
        self,
        strategy: str,
        rank: int,
        metrics: dict[str, float],
    ) -> str:
        """Generate a preset ID based on strategy and rank."""
        sharpe = metrics.get("sharpe_ratio", 0)
        
        if sharpe > 1.5:
            quality = "excellent"
        elif sharpe > 1.0:
            quality = "good"
        else:
            quality = "moderate"
        
        return f"auto_{quality}_v{rank}"
    
    def _calculate_confidence(self, metrics: dict[str, float]) -> float:
        """Calculate confidence score for a preset."""
        sharpe = metrics.get("sharpe_ratio", 0)
        win_rate = metrics.get("win_rate", 0)
        profit_factor = metrics.get("profit_factor", 0)
        max_dd = metrics.get("max_drawdown", 1)
        
        # Weighted scoring
        score = 0.0
        score += min(sharpe / 2.0, 0.3)  # Max 0.3 for Sharpe
        score += min(win_rate, 0.25)     # Max 0.25 for win rate
        score += min(profit_factor / 4.0, 0.25)  # Max 0.25 for PF
        score += max(0.2 - max_dd, 0)    # Max 0.2 for low drawdown
        
        return min(score, 1.0)
    
    def save_candidates(
        self,
        candidates: list[PresetCandidate],
        output_file: str | None = None,
    ) -> None:
        """Save preset candidates to file."""
        output_dir = Path(settings.RESULTS_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        if not output_file:
            output_file = str(output_dir / "preset_candidates.json")
        
        data = [
            {
                "strategy": c.strategy,
                "symbol": c.symbol,
                "preset_id": c.preset_id,
                "params": c.params,
                "metrics": c.metrics,
                "confidence": c.confidence,
            }
            for c in candidates
        ]
        
        with open(output_file, "w") as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Saved {len(candidates)} candidates to {output_file}")
