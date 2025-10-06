#!/usr/bin/env python3
"""
ops/m23_dream_engine.py — M23 Dream Engine

Offline imagination and simulation system that enables the trading organism to explore
alternate realities, test hypothetical scenarios, and learn from synthetic experiences.

Dream Capabilities:
- Load archived models from M21 memory vault for resurrection
- Generate synthetic market scenarios with varied characteristics
- Simulate performance across diverse market conditions
- Archive dream results and learning insights
- Enable continuous background innovation without live capital risk

The organism now "dreams" during sleep cycles, exploring "what if" scenarios
that improve its waking trading performance through offline hypothesis testing.
"""

import os
import json
import random
import numpy as np
import pandas as pd
import joblib
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from sklearn.metrics import accuracy_score, classification_report
from sklearn.preprocessing import StandardScaler

# Import paths from completed systems
MEMORY_VAULT = os.path.join("data", "memory_vault")
DREAM_ARCHIVE = os.path.join("data", "dreams")
LINEAGE_INDEX = os.path.join(MEMORY_VAULT, "lineage_index.json")

# Create dream archive directory
os.makedirs(DREAM_ARCHIVE, exist_ok=True)

def load_ancestral_models(limit: int = None) -> List[str]:
    """
    Discover fossils available for resurrection in dream simulations.

    Args:
        limit: Maximum number of models to return (None for all)

    Returns:
        List of model file paths from memory vault
    """
    if not os.path.exists(MEMORY_VAULT):
        print("[M23] 🛌 Memory vault not found - no ancestral models to dream with")
        return []

    model_paths = []
    for item in os.listdir(MEMORY_VAULT):
        vault_path = os.path.join(MEMORY_VAULT, item)
        if os.path.isdir(vault_path):
            # Look for .joblib files in each generation directory
            for filename in os.listdir(vault_path):
                if filename.endswith(".joblib"):
                    model_paths.append(os.path.join(vault_path, filename))

    print(f"[M23] 🧬 Found {len(model_paths)} ancestral models in memory vault")
    return model_paths[:limit] if limit else model_paths

def select_ancestral_model(model_paths: List[str] = None) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Randomly select an ancestral model for resurrection and dream exploration.

    Includes metadata about the selected model for dream context.

    Returns:
        Tuple of (model_path, metadata) or None if no models available
    """
    if model_paths is None:
        model_paths = load_ancestral_models()

    if not model_paths:
        return None

    # Select model randomly to encourage broad dream exploration
    selected_path = random.choice(model_paths)

    # Extract generation tag from path
    generation = os.path.basename(os.path.dirname(selected_path))

    # Load metadata if available
    metadata_path = selected_path.replace(".joblib", ".json")
    metadata = {}
    if os.path.exists(metadata_path):
        try:
            metadata = json.load(open(metadata_path))
        except Exception as e:
            print(f"[M23] ⚠️ Failed to load metadata for {selected_path}: {e}")

    return selected_path, {
        "model_path": selected_path,
        "generation": generation,
        "metadata": metadata
    }

def generate_dream_scenario(features_count: int = 10, data_points: int = 2000,
                          market_regime: str = "normal") -> Tuple[np.ndarray, np.ndarray]:
    """
    Generate synthetic market data for dream simulations.

    Creates diverse market scenarios to test policy performance across conditions.

    Args:
        features_count: Number of feature dimensions
        data_points: Number of data points to generate
        market_regime: Market condition type ('normal', 'volatile', 'trending', 'chaos')

    Returns:
        Tuple of (X_features, y_labels) for model testing
    """
    rng = np.random.default_rng()

    # Base market characteristics
    base_volatility = 0.05
    trend_strength = 0.0

    if market_regime == "volatile":
        base_volatility = 0.15
    elif market_regime == "trending":
        trend_strength = 0.2
    elif market_regime == "chaos":
        base_volatility = 0.25
        # Add chaos: correlated random shocks
        chaos_factor = rng.normal(0, 0.1, data_points)

    # Generate base features with temporal correlations
    X = rng.normal(0, 1, (data_points, features_count))

    # Add temporal autocorrelation (markets aren't pure noise)
    for i in range(1, data_points):
        X[i] += 0.7 * X[i-1] + rng.normal(0, 0.3, features_count)

    # Add volatility scaling based on regime
    X *= np.sqrt(base_volatility)

    # Add trending behavior if specified
    if trend_strength > 0:
        trend_component = np.linspace(-trend_strength, trend_strength, data_points)
        X[:, 0] += trend_component  # Primary trend in first feature

    # Generate synthetic labels (trading signals) with realistic predictability
    # In real markets, signals have edge but aren't deterministic
    market_signal = (X @ rng.normal(0, 0.1, features_count))  # Weak linear combination
    noise = rng.normal(0, 1.0, data_points)
    combined_signal = market_signal + noise

    # Add regime-specific effects to labels
    if market_regime == "trending":
        # Trending markets have more persistent signals
        trend_bias = np.convolve(np.sign(combined_signal), np.ones(20), mode='same') / 20
        combined_signal += trend_bias * 0.3
    elif market_regime == "chaos":
        # Chaotic markets have extreme noise injected
        combined_signal += chaos_factor

    # Convert to binary classification (buy/sell/hold)
    y_probability = 1 / (1 + np.exp(-combined_signal))  # Sigmoid
    y = (y_probability > 0.5).astype(int)

    return X, y

def evaluate_ancestral_model(model_info: Dict[str, Any], X: np.ndarray,
                           y: np.ndarray, regime: str) -> Dict[str, Any]:
    """
    Evaluate an ancestral model's performance in dream scenario.

    Loads the archived model, runs predictions, and computes metrics.

    Args:
        model_info: Model metadata from ancestral selection
        X: Feature data for simulation
        y: True labels for evaluation
        regime: Market regime being tested

    Returns:
        Comprehensive evaluation results
    """
    model_path = model_info["model_path"]

    try:
        # Load ancestral model
        model = joblib.load(model_path)
    except Exception as e:
        return {
            "status": "error",
            "error": f"Failed to load model: {e}",
            "dream_type": "resurrection_failure"
        }

    try:
        # Generate predictions
        y_pred = model.predict(X)

        # Compute performance metrics
        accuracy = float(accuracy_score(y, y_pred))

        # Simulate P&L (simplified - in real dreams would include slippage, fees)
        position_returns = np.random.uniform(-0.002, 0.003, len(y))  # Random position returns
        pnl_simulation = float(np.mean(y_pred == y) * np.mean(position_returns))

        # Additional metrics
        true_positives = np.sum((y_pred == 1) & (y == 1))
        false_positives = np.sum((y_pred == 1) & (y == 0))
        precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0

        return {
            "status": "success",
            "dream_type": "ancestral_simulation",
            "ancestral_generation": model_info["generation"],
            "market_regime": regime,
            "accuracy_score": accuracy,
            "simulated_pnl": pnl_simulation,
            "precision_score": float(precision),
            "sample_size": len(y),
            "feature_dimensions": X.shape[1]
        }

    except Exception as e:
        return {
            "status": "error",
            "error": f"Model evaluation failed: {e}",
            "dream_type": "runtime_failure"
        }

def archive_dream_results(dream_data: Dict[str, Any]) -> str:
    """
    Save dream results to persistent archive.

    Args:
        dream_data: Complete dream session results

    Returns:
        Path where dream was archived
    """
    # Create dream filename with timestamp
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dream_gen = dream_data.get("ancestral_generation", "unknown")
    dream_file = f"dream_{dream_gen}_{timestamp}.json"

    archive_path = os.path.join(DREAM_ARCHIVE, dream_file)

    try:
        with open(archive_path, 'w') as f:
            json.dump(dream_data, f, indent=2, default=str)
        print(f"[M23] 💤 Dream archived: {archive_path}")
        return archive_path
    except Exception as e:
        print(f"[M23] ⚠️ Failed to archive dream: {e}")
        return ""

def generate_dream_report() -> Dict[str, Any]:
    """
    Generate summary statistics across all archived dreams.

    Returns:
        Comprehensive dream analysis
    """
    if not os.path.exists(DREAM_ARCHIVE):
        return {"status": "no_dreams", "total_dreams": 0}

    dreams = []
    for filename in os.listdir(DREAM_ARCHIVE):
        if filename.endswith(".json"):
            try:
                with open(os.path.join(DREAM_ARCHIVE, filename)) as f:
                    dream = json.load(f)
                    dreams.append(dream)
            except Exception as e:
                print(f"[M23] ⚠️ Failed to load dream {filename}: {e}")

    if not dreams:
        return {"status": "no_dreams", "total_dreams": 0}

    # Analyze dream patterns
    successful_dreams = [d for d in dreams if d.get("status") == "success"]
    failed_dreams = [d for d in dreams if d.get("status") == "error"]

    avg_accuracy = np.mean([d.get("accuracy_score", 0) for d in successful_dreams])
    avg_pnl = np.mean([d.get("simulated_pnl", 0) for d in successful_dreams])

    # Group by market regime
    regime_performance = {}
    for dream in successful_dreams:
        regime = dream.get("market_regime", "unknown")
        if regime not in regime_performance:
            regime_performance[regime] = []
        regime_performance[regime].append(dream.get("accuracy_score", 0))

    return {
        "total_dreams": len(dreams),
        "successful_dreams": len(successful_dreams),
        "failed_dreams": len(failed_dreams),
        "average_accuracy": float(avg_accuracy) if successful_dreams else 0,
        "average_simulated_pnl": float(avg_pnl) if successful_dreams else 0,
        "regime_performance": {k: float(np.mean(v)) for k, v in regime_performance.items()},
        "dream_frequency": len(dreams) / max(1, (datetime.utcnow().timestamp() - os.path.getctime(DREAM_ARCHIVE))) * 86400  # dreams per day
    }

def dream_cycle(dream_duration_minutes: int = 30) -> Dict[str, Any]:
    """
    Execute a complete dream cycle - load ancestral model, generate scenario,
    evaluate performance, and archive results.

    Args:
        dream_duration_minutes: Minutes to spend in full dream state

    Returns:
        Summary of dream cycle outcomes
    """
    start_time = datetime.utcnow()
    print(f"[M23] 🛌 Dreaming cycle initiated at {start_time.strftime('%H:%M:%S')}")

    cycle_results = {
        "cycle_start": start_time.isoformat(),
        "dreams_completed": 0,
        "successful_resurrections": 0,
        "market_regimes_explored": set(),
        "insights_discovered": [],
        "warnings_issued": []
    }

    # Execute multiple dreams within the cycle
    dream_count = 0
    max_dreams = min(5, int(dream_duration_minutes / 6))  # Roughly 6 minutes per dream

    while dream_count < max_dreams:
        # Select ancestral model for resurrection
        model_selection = select_ancestral_model()
        if not model_selection:
            cycle_results["warnings_issued"].append("No ancestral models available for resurrection")
            break

        model_path, model_info = model_selection

        # Choose market regime for this dream
        regimes = ["normal", "volatile", "trending", "chaos"]
        selected_regime = random.choice(regimes)

        # Generate dream scenario
        X_dream, y_dream = generate_dream_scenario(market_regime=selected_regime)

        # Evaluate ancestral model in dream
        evaluation = evaluate_ancestral_model(model_info, X_dream, y_dream, selected_regime)

        if evaluation["status"] == "success":
            cycle_results["successful_resurrections"] += 1
            cycle_results["market_regimes_explored"].add(selected_regime)

            # Analyze insights
            accuracy = evaluation.get("accuracy_score", 0)
            pnl = evaluation.get("simulated_pnl", 0)

            if accuracy > 0.6:
                cycle_results["insights_discovered"].append(f"Strong performer: {model_info['generation']} in {selected_regime}")
            elif pnl < -0.001:
                cycle_results["insights_discovered"].append(f"P&L concern: {model_info['generation']} shows losses in {selected_regime}")

        # Archive dream results
        evaluation.update({
            "cycle_timestamp": start_time.isoformat(),
            "dream_number": dream_count + 1,
            "execution_metadata": model_info
        })

        archive_dream_results(evaluation)
        dream_count += 1

    # Complete cycle
    end_time = datetime.utcnow()
    cycle_duration = (end_time - start_time).total_seconds()

    cycle_results.update({
        "cycle_end": end_time.isoformat(),
        "cycle_duration_seconds": cycle_duration,
        "dreams_per_second": cycle_results["dreams_completed"] / max(1, cycle_duration)
    })

    print(f"[M23] 💭 Dream cycle complete: {cycle_results['dreams_completed']} dreams in {cycle_duration:.0f}s")
    if cycle_results["insights_discovered"]:
        print(f"[M23] 🔍 Insights: {len(cycle_results['insights_discovered'])} discoveries made")

    return cycle_results

def main():
    """Main dream execution entry point."""
    print("[M23] 🌙 Trading Organism Dream Engine activating...")

    # Check for available ancestors
    ancestors = load_ancestral_models()
    if not ancestors:
        print("[M23] 🛌 No ancestral models found. Dreams require M21 memory first.")
        print("[M23] 💡 Try running M21 memory manager to archive models for resurrection.")
        return 1

    print(f"[M23] 🧬 {len(ancestors)} ancestors available for dream resurrection")

    # Execute dream cycle
    try:
        result = dream_cycle(15)  # 15-minute dream cycle

        # Generate dream report
        report = generate_dream_report()

        print(f"\n[M23] 📊 Dream Report: {report['total_dreams']} total dreams, {report['successful_dreams']} successful")
        print(".3f"        print(".6f")

    except KeyboardInterrupt:
        print("[M23] 💭 Dream cycle interrupted by user")
    except Exception as e:
        print(f"[M23] ⚠️ Dream cycle error: {e}")
        return 1

    print("[M23] 🌅 Dream complete. Awake and wiser.")
    return 0

if __name__ == "__main__":
    exit(main())
