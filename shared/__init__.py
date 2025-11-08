"""
Shared utilities used by strategies and screeners.

Minimal implementations are provided to satisfy unit tests without imposing
external dependencies. These helpers cover:

- Cooldown tracking for per-symbol rate limiting
- Score-to-confidence mapping
- Simple listing/meme utility functions for stops/targets and scoring
"""

from .cooldown import CooldownTracker
from .listing_utils import (
    ListingMetrics,
    compute_listing_metrics,
    generate_listing_targets,
)
from .meme_utils import (
    MemeMetrics,
    compute_meme_metrics,
    generate_meme_bracket,
)
from .signal_math import confidence_from_score

__all__ = [
    "CooldownTracker",
    "confidence_from_score",
    "generate_listing_targets",
    "compute_listing_metrics",
    "ListingMetrics",
    "generate_meme_bracket",
    "compute_meme_metrics",
    "MemeMetrics",
]
