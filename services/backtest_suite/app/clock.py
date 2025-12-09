"""Simulation clock for backtest replay."""

from datetime import datetime, timezone
from typing import Iterator


class SimulationClock:
    """Manages simulation time for backtest replay.
    
    Provides a deterministic clock that advances through historical data
    without relying on real wall-clock time.
    """
    
    def __init__(self, start_ts: int, end_ts: int, step_ms: int = 60_000):
        """Initialize the simulation clock.
        
        Args:
            start_ts: Start timestamp in milliseconds
            end_ts: End timestamp in milliseconds
            step_ms: Time step in milliseconds (default 1 minute)
        """
        self.start_ts = start_ts
        self.end_ts = end_ts
        self.step_ms = step_ms
        self.current_ts = start_ts
    
    def now(self) -> int:
        """Get current simulation time in milliseconds."""
        return self.current_ts
    
    def now_dt(self) -> datetime:
        """Get current simulation time as datetime."""
        return datetime.fromtimestamp(self.current_ts / 1000, tz=timezone.utc)
    
    def advance(self, steps: int = 1) -> int:
        """Advance the clock by the specified number of steps.
        
        Args:
            steps: Number of steps to advance
            
        Returns:
            New current timestamp
        """
        self.current_ts = min(self.current_ts + steps * self.step_ms, self.end_ts)
        return self.current_ts
    
    def advance_to(self, ts: int) -> int:
        """Advance the clock to a specific timestamp.
        
        Args:
            ts: Target timestamp in milliseconds
            
        Returns:
            New current timestamp
        """
        self.current_ts = min(max(ts, self.current_ts), self.end_ts)
        return self.current_ts
    
    def is_finished(self) -> bool:
        """Check if simulation has reached the end."""
        return self.current_ts >= self.end_ts
    
    def progress(self) -> float:
        """Get simulation progress as fraction (0.0 to 1.0)."""
        total = self.end_ts - self.start_ts
        if total <= 0:
            return 1.0
        elapsed = self.current_ts - self.start_ts
        return min(elapsed / total, 1.0)
    
    def iter_steps(self) -> Iterator[int]:
        """Iterate through all time steps.
        
        Yields:
            Current timestamp at each step
        """
        while not self.is_finished():
            yield self.current_ts
            self.advance()
    
    def reset(self) -> None:
        """Reset clock to start time."""
        self.current_ts = self.start_ts
