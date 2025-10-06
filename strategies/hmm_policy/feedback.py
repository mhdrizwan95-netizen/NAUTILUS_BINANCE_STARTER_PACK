#!/usr/bin/env python3
# strategies/hmm_policy/feedback.py — M15: Comprehensive feedback logging for online learning
import csv
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
import threading
import time

@dataclass
class FeedbackEvent:
    """Rich feedback record for every trade attempt and outcome."""
    ts_ns: int  # Timestamp in nanoseconds
    symbol: str
    macro_state: int
    micro_state: int
    confidence: float
    side: str  # BUY/SELL/HOLD
    qty: float  # Requested quantity
    fill_px: float  # Actual fill price (or ref price for blocked)
    ref_mid_px: float  # Reference mid price for ΔPnL calculation
    delta_pnl: float  # Realized ΔPnL (0 for blocked trades)
    guardrail: Optional[str] = None  # Reason for block/rejection, or None

    def to_row(self) -> list:
        """Convert to CSV row format."""
        return [
            self.ts_ns,
            self.symbol,
            self.macro_state,
            self.micro_state,
            self.confidence,
            self.side,
            self.qty,
            self.fill_px,
            self.ref_mid_px,
            self.delta_pnl,
            self.guardrail or ""
        ]

@dataclass
class FeedbackMetrics:
    """Aggregated metrics from feedback log."""
    total_events: int = 0
    trades_completed: int = 0
    trades_blocked: int = 0
    avg_win_when_taken: float = 0.0
    avg_loss_when_taken: float = 0.0
    win_rate: float = 0.5
    avg_conf_on_win: float = 0.5
    avg_conf_on_loss: float = 0.5

class FeedbackLogger:
    """
    Thread-safe persistent feedback logger for trade outcomes and guardrail blocks.
    Critical for online learning signal quality.
    """

    def __init__(self, out_dir: Path, buffer_size: int = 1000):
        """
        Initialize feedback logger.

        Args:
            out_dir: Directory to save feedback_log.csv
            buffer_size: Memory buffer before disk flush
        """
        self.out_dir = Path(out_dir)
        self.log_path = self.out_dir / "feedback_log.csv"
        self.metrics_path = self.out_dir / "feedback_metrics.json"
        self.lock = threading.Lock()
        self.buffer = []
        self.buffer_size = buffer_size
        self._ensure_csv_exists()

    def _ensure_csv_exists(self):
        """Create CSV file with headers if it doesn't exist."""
        self.out_dir.mkdir(parents=True, exist_ok=True)

        if not self.log_path.exists():
            with open(self.log_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "ts_ns", "symbol", "macro_state", "micro_state",
                    "confidence", "side", "qty", "fill_px", "ref_mid_px",
                    "delta_pnl", "guardrail"
                ])

    def record_trade(self,
                    ts_ns: int,
                    symbol: str,
                    macro_state: int,
                    micro_state: int,
                    confidence: float,
                    side: str,
                    qty: float,
                    fill_px: float,
                    ref_mid_px: float,
                    delta_pnl: float,
                    guardrail: Optional[str] = None):
        """
        Record a completed trade or guardrail block.

        For blocked trades: set qty=0, fill_px=ref_mid_px, delta_pnl=0, include guardrail reason
        For completed trades: include actual fill details
        """
        event = FeedbackEvent(
            ts_ns=ts_ns,
            symbol=symbol,
            macro_state=macro_state,
            micro_state=micro_state,
            confidence=confidence,
            side=side,
            qty=qty,
            fill_px=fill_px,
            ref_mid_px=ref_mid_px,
            delta_pnl=delta_pnl,
            guardrail=guardrail
        )

        self.write(event)

    def write(self, event: FeedbackEvent):
        """Write feedback event with buffering."""
        with self.lock:
            self.buffer.append(event)

            if len(self.buffer) >= self.buffer_size:
                self._flush_buffer()

    def _flush_buffer(self):
        """Flush buffered events to disk."""
        if not self.buffer:
            return

        with open(self.log_path, 'a', newline='') as f:
            writer = csv.writer(f)
            for event in self.buffer:
                writer.writerow(event.to_row())

        self.buffer.clear()

    def flush(self):
        """Force flush any buffered events to disk."""
        with self.lock:
            if self.buffer:
                self._flush_buffer()

    def compute_metrics(self, window_days: int = 7) -> FeedbackMetrics:
        """
        Compute recent feedback metrics for monitoring.

        Args:
            window_days: Lookback period in days for metrics calculation

        Returns:
            Aggregated feedback metrics
        """
        if not self.log_path.exists():
            return FeedbackMetrics()

        # Read recent events (rough windowing by row count to avoid timestamp parsing)
        recent_events = []
        max_rows = 10000  # Last ~10K events as reasonable window

        try:
            with open(self.log_path, 'r', newline='') as f:
                reader = csv.DictReader(f)
                events = list(reader)[-max_rows:]  # Last N events

                for row in events:
                    try:
                        recent_events.append(FeedbackEvent(
                            ts_ns=int(row['ts_ns']),
                            symbol=row['symbol'],
                            macro_state=int(row['macro_state']),
                            micro_state=int(row['micro_state']),
                            confidence=float(row['confidence']),
                            side=row['side'],
                            qty=float(row['qty']),
                            fill_px=float(row['fill_px']),
                            ref_mid_px=float(row['ref_mid_px']),
                            delta_pnl=float(row['delta_pnl']),
                            guardrail=row['guardrail'] if row['guardrail'] else None
                        ))
                    except (ValueError, KeyError):
                        continue  # Skip malformed rows

        except (FileNotFoundError, csv.Error):
            return FeedbackMetrics()

        # Compute metrics
        total_events = len(recent_events)
        trades_completed = sum(1 for e in recent_events if e.qty > 0 and e.delta_pnl != 0)
        trades_blocked = sum(1 for e in recent_events if e.guardrail is not None)

        trade_pnls = [e.delta_pnl for e in recent_events if e.qty > 0 and e.delta_pnl != 0]
        wins = [p for p in trade_pnls if p > 0]
        losses = [p for p in trade_pnls if p < 0]

        win_confs = [e.confidence for e in recent_events if e.qty > 0 and e.delta_pnl > 0]
        loss_confs = [e.confidence for e in recent_events if e.qty > 0 and e.delta_pnl < 0]

        metrics = FeedbackMetrics(
            total_events=total_events,
            trades_completed=trades_completed,
            trades_blocked=trades_blocked,
            avg_win_when_taken=sum(wins) / len(wins) if wins else 0.0,
            avg_loss_when_taken=sum(losses) / len(losses) if losses else 0.0,
            win_rate=len(wins) / len(trade_pnls) if trade_pnls else 0.5,
            avg_conf_on_win=sum(win_confs) / len(win_confs) if win_confs else 0.5,
            avg_conf_on_loss=sum(loss_confs) / len(loss_confs) if loss_confs else 0.5
        )

        return metrics

    def get_recent_events(self, limit: int = 100) -> list[FeedbackEvent]:
        """
        Get most recent feedback events for analysis.

        Args:
            limit: Maximum number of events to return

        Returns:
            List of most recent FeedbackEvents
        """
        if not self.log_path.exists():
            return []

        events = []
        try:
            with open(self.log_path, 'r', newline='') as f:
                reader = csv.DictReader(f)
                rows = list(reader)[-limit:]  # Last N rows

                for row in rows:
                    try:
                        events.append(FeedbackEvent(
                            ts_ns=int(row['ts_ns']),
                            symbol=row['symbol'],
                            macro_state=int(row['macro_state']),
                            micro_state=int(row['micro_state']),
                            confidence=float(row['confidence']),
                            side=row['side'],
                            qty=float(row['qty']),
                            fill_px=float(row['fill_px']),
                            ref_mid_px=float(row['ref_mid_px']),
                            delta_pnl=float(row['delta_pnl']),
                            guardrail=row['guardrail'] if row['guardrail'] else None
                        ))
                    except (ValueError, KeyError):
                        continue

        except (FileNotFoundError, csv.Error):
            pass

        return events

    def get_state_transition_examples(self, limit: int = 1000) -> Dict[tuple, list]:
        """
        Group feedback by (macro_state, micro_state) for online learning.

        Returns:
            Dict mapping (M,S) -> list of feedback events for that state
        """
        events = self.get_recent_events(limit)
        grouped = {}

        for event in events:
            key = (event.macro_state, event.micro_state)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(event)

        return grouped

# Global logger instance (initialized per data directory)
_global_logger: Optional[FeedbackLogger] = None

def get_feedback_logger(data_dir: Path) -> FeedbackLogger:
    """Get or create global feedback logger instance."""
    global _global_logger
    if _global_logger is None or _global_logger.out_dir != data_dir:
        _global_logger = FeedbackLogger(data_dir)
    return _global_logger
