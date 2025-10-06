#!/usr/bin/env python3
"""
ops/m17_train_micro.py — Train Micro HMM Policies per Regime

Reads feedback_log.csv and trains regime-specific policy models:
- Automatically partitions data by macro regimes detected in feedback
- Trains separate SGD classifiers for each regime: Calm, Trend, Chaos
- Saves policy_v{Calm|Trend|Chaos}.joblib for hierarchical switching

Usage:
    python ops/m17_train_micro.py --feedback data/processed/feedback_log.csv --macro-model ml_service/model_store/macro_regime_hmm.joblib

Outputs:
    - ml_service/model_store/policy_Calm.joblib
    - ml_service/model_store/policy_Trend.joblib
    - ml_service/model_store/policy_Chaos.joblib
    - data/processed/m17/micro_training_stats.json
    - data/processed/m17/micro_learning_curves.png
"""

import os
import json
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
from collections import defaultdict
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split

# Import the hierarchical HMM classes
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ml_service.hierarchical_hmm import MacroRegimeHMM, HierarchicalPolicy

OUT_DIR = "data/processed/m17"
MODEL_DIR = "ml_service/model_store"

def load_feedback_with_macro_regimes(feedback_path: str, macro_model_path: str) -> pd.DataFrame:
    """
    Load feedback log and augment with macro regime classifications.

    Since the feedback_log.csv doesn't contain macro regime features during collection,
    we need to reconstruct them or use simplified regime estimation.
    """
    print(f"Loading feedback from {feedback_path}")

    # Load feedback data (expecting columns: ts_ns, symbol, macro_state, micro_state, confidence, side, qty, fill_px, ref_mid_px, delta_pnl, guardrail)
    df = pd.read_csv(feedback_path)

    # Basic data validation
    required_cols = ['ts_ns', 'macro_state', 'micro_state', 'confidence', 'side', 'delta_pnl']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns in feedback: {missing_cols}")

    print(f"Loaded {len(df)} feedback records")

    # For now, we'll use the existing macro_state field from feedback as regime labels
    # In a real implementation, we'd compute macro features from market data and classify
    if 'macro_state' in df.columns:
        # Map existing macro_state to regime names
        regime_map = {0: 'Calm', 1: 'Trend', 2: 'Chaos'}
        df['regime'] = df['macro_state'].map(regime_map).fillna('Calm')
        print(f"Using macro_state for regime labels: {df['regime'].value_counts().to_dict()}")
    else:
        print("Warning: No macro_state column, defaulting all to 'Calm' regime")
        df['regime'] = 'Calm'

    return df

def prepare_features_for_regime(df: pd.DataFrame) -> np.ndarray:
    """
    Extract or reconstruct features for policy modeling within a regime.

    Since the feedback log may not have raw features, we'll use available state info
    or create dummy features for demonstration.
    """
    features = []

    # Try to use available state features
    if 'macro_state' in df.columns and 'micro_state' in df.columns and 'confidence' in df.columns:
        # Create one-hot encodings + confidence
        macro_oh = pd.get_dummies(df['macro_state'].astype(int), prefix='macro').values
        micro_oh = pd.get_dummies(df['micro_state'].astype(int), prefix='micro').values
        conf = df['confidence'].values.reshape(-1, 1)

        features = np.hstack([macro_oh, micro_oh, conf])
        print(f"Using state-based features: {features.shape[1]} dimensions")
    else:
        # Fallback: random features for demonstration
        print("Warning: Using random features for demonstration")
        features = np.random.randn(len(df), 6)

    return features

def create_action_labels(df: pd.DataFrame) -> np.ndarray:
    """
    Create action labels from feedback data.

    Actions: -1 (SELL), 0 (HOLD), 1 (BUY)
    We'll infer from side and pnl data or use direct action if available.
    """
    if 'side' in df.columns:
        # Map side to action: BUY->1, SELL->-1, others->0
        side_map = {'BUY': 1, 'SELL': -1}
        actions = df['side'].map(side_map).fillna(0).astype(int).values
    else:
        # Fallback: use pnl sign as action signal (simplified)
        actions = np.sign(df.get('delta_pnl', 0).fillna(0))

    # Ensure we have the expected action range (-1, 0, 1)
    actions = np.clip(actions, -1, 1)

    print(f"Action distribution: {np.bincount(actions + 1, minlength=3)} (SELL/HOLD/BUY)")
    return actions

def train_regime_policy(df_regime: pd.DataFrame, regime_name: str, test_size: float = 0.2) -> Tuple[SGDClassifier, Dict[str, Any]]:
    """
    Train a policy model for a specific regime.

    Args:
        df_regime: Feedback data for this regime
        regime_name: Name of the regime
        test_size: Fraction of data to use for testing

    Returns:
        Trained model and training statistics
    """
    print(f"Training policy for regime '{regime_name}' with {len(df_regime)} samples")

    if len(df_regime) < 50:
        print(f"Warning: Very few samples for {regime_name}, results may be poor")

    # Prepare features and labels
    X = prepare_features_for_regime(df_regime)
    y = create_action_labels(df_regime)

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=42, stratify=y
    )

    # Train model
    model = SGDClassifier(
        loss='log_loss',  # Multi-class logistic regression
        learning_rate='adaptive',
        eta0=0.01,
        max_iter=1000,
        random_state=42,
        class_weight='balanced',  # Handle imbalanced action classes
        alpha=0.01  # L2 regularization
    )

    model.fit(X_train, y_train)

    # Evaluate
    train_score = model.score(X_train, y_train)
    test_score = model.score(X_test, y_test) if len(X_test) > 0 else None

    y_pred = model.predict(X_test) if len(X_test) > 0 else []
    conf_matrix = confusion_matrix(y_test, y_pred) if len(X_test) > 0 else None
    class_report = classification_report(y_test, y_pred, target_names=['SELL', 'HOLD', 'BUY'],
                                       output_dict=True) if len(X_test) > 0 else {}

    stats = {
        'regime': regime_name,
        'train_samples': len(X_train),
        'test_samples': len(X_test) if len(X_test) > 0 else 0,
        'train_accuracy': float(train_score),
        'test_accuracy': float(test_score) if test_score is not None else None,
        'confusion_matrix': conf_matrix.tolist() if conf_matrix is not None else None,
        'classification_report': class_report,
        'feature_importance': None  # Could add coefficient analysis
    }

    return model, stats

def train_all_micro_policies(feedback_df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """
    Train policies for all available regimes.

    Args:
        feedback_df: Full feedback dataframe with regime labels

    Returns:
        Dictionary mapping regime names to training results
    """
    regime_groups = feedback_df.groupby('regime')
    training_results = {}

    print(f"Found {len(regime_groups)} regimes in feedback data")

    for regime_name, df_regime in regime_groups:
        try:
            model, stats = train_regime_policy(df_regime, regime_name)
            training_results[regime_name] = {
                'model': model,
                'stats': stats
            }
            print(f"✅ Trained policy for {regime_name}")

        except Exception as e:
            print(f"❌ Failed to train policy for {regime_name}: {e}")
            training_results[regime_name] = {
                'error': str(e),
                'stats': {'regime': regime_name, 'train_samples': len(df_regime)}
            }

    return training_results

def save_micro_policies(training_results: Dict[str, Dict[str, Any]]) -> None:
    """Save trained policy models to the model store."""
    os.makedirs(MODEL_DIR, exist_ok=True)

    for regime_name, result in training_results.items():
        if 'model' in result:
            model = result['model']
            model_path = os.path.join(MODEL_DIR, f"policy_{regime_name}.joblib")

            # Save with metadata
            bundle = {
                'policy': model,
                'metadata': {
                    'regime': regime_name,
                    'training_stats': result['stats'],
                    'trained_at': pd.Timestamp.now().isoformat()
                }
            }

            import joblib
            joblib.dump(bundle, model_path)
            print(f"Saved policy for {regime_name} to {model_path}")

def create_training_report(training_results: Dict[str, Dict[str, Any]]) -> None:
    """Generate and save training report and plots."""
    os.makedirs(OUT_DIR, exist_ok=True)

    # Save detailed stats
    summary = {}
    for regime_name, result in training_results.items():
        if 'stats' in result:
            summary[regime_name] = result['stats']

    stats_file = os.path.join(OUT_DIR, "micro_training_stats.json")
    with open(stats_file, 'w') as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"Saved training stats to {stats_file}")

    # Create plots
    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle("M17 Micro Policy Training Results", fontsize=16)

    # Plot 1: Accuracy comparison
    ax1 = axes[0, 0]
    regimes = []
    train_accs = []
    test_accs = []

    for regime_name, result in training_results.items():
        if 'stats' in result:
            stats = result['stats']
            regimes.append(regime_name)
            train_accs.append(stats.get('train_accuracy', 0))
            test_accs.append(stats.get('test_accuracy') or 0)

    x = np.arange(len(regimes))
    width = 0.35
    ax1.bar(x - width/2, train_accs, width, label='Train', alpha=0.8)
    ax1.bar(x + width/2, test_accs, width, label='Test', alpha=0.8)
    ax1.set_xlabel('Regime')
    ax1.set_ylabel('Accuracy')
    ax1.set_title('Policy Accuracy by Regime')
    ax1.set_xticks(x)
    ax1.set_xticklabels(regimes)
    ax1.legend()

    # Plot 2: Sample count per regime
    ax2 = axes[0, 1]
    sample_counts = []
    for regime_name, result in training_results.items():
        if 'stats' in result:
            sample_counts.append(result['stats'].get('train_samples', 0))

    ax2.bar(regimes, sample_counts)
    ax2.set_xlabel('Regime')
    ax2.set_ylabel('Training Samples')
    ax2.set_title('Training Data Size by Regime')
    ax2.set_yscale('log')

    # Plot 3: Confusion matrix for first regime (if available)
    ax3 = axes[1, 0]
    first_regime = next(iter(training_results.keys()))
    if first_regime in training_results and 'stats' in training_results[first_regime]:
        stats = training_results[first_regime]['stats']
        if stats.get('confusion_matrix'):
            cm = np.array(stats['confusion_matrix'])
            cm_norm = cm.astype('float') / cm.sum(axis=1)[:, np.newaxis]

            im = ax3.imshow(cm_norm, cmap='Blues', vmin=0, vmax=1)
            ax3.set_title(f'Confusion Matrix: {first_regime}')
            ax3.set_xlabel('Predicted')
            ax3.set_ylabel('Actual')
            ax3.set_xticks([0, 1, 2])
            ax3.set_yticks([0, 1, 2])
            ax3.set_xticklabels(['SELL', 'HOLD', 'BUY'])
            ax3.set_yticklabels(['SELL', 'HOLD', 'BUY'])
            plt.colorbar(im, ax=ax3)

    # Plot 4: Classification report
    ax4 = axes[1, 1]
    ax4.axis('off')
    report_text = "Classification Reports:\n\n"
    for regime_name, result in training_results.items():
        if 'stats' in result and result['stats'].get('test_accuracy'):
            acc = result['stats']['test_accuracy']
            report_text += f"{regime_name}: {acc:.3f}\n"
    ax4.text(0.1, 0.9, report_text, transform=ax4.transAxes,
             fontsize=10, verticalalignment='top', fontfamily='monospace')

    plt.tight_layout()

    plot_file = os.path.join(OUT_DIR, "micro_learning_curves.png")
    plt.savefig(plot_file, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved training plots to {plot_file}")

def main():
    parser = argparse.ArgumentParser(description="Train M17 Micro Policy Models per Regime")
    parser.add_argument("--feedback", required=True, help="Path to feedback_log.csv")
    parser.add_argument("--macro-model", help="Path to trained macro regime model (optional)")
    parser.add_argument("--test-size", type=float, default=0.2, help="Test data fraction")

    args = parser.parse_args()

    print(f"M17 Micro Policy Training")
    print(f"Feedback file: {args.feedback}")
    print(f"Macro model: {args.macro_model}")
    print(f"Test size: {args.test_size}")

    try:
        # Load feedback data with regime labels
        feedback_df = load_feedback_with_macro_regimes(args.feedback, args.macro_model)

        # Train policies for each regime
        training_results = train_all_micro_policies(feedback_df)

        # Save models
        save_micro_policies(training_results)

        # Generate reports and plots
        create_training_report(training_results)

        print("✅ M17 Micro policy training completed successfully")
        print(f"Trained {len(training_results)} regime policies")
        print(f"See {OUT_DIR}/micro_training_stats.json for details")

        return 0

    except Exception as e:
        print(f"ERROR: Micro policy training failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())
