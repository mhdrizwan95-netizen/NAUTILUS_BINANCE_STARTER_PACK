def confidence_from_score(score: float) -> float:
    """
    Convert a raw score (e.g. sentiment score) into a confidence value between 0.0 and 1.0.
    """
    # Simple sigmoid-like normalization or clamping
    # Assuming score is roughly -1.0 to 1.0 or similar scale
    # For now, just clamping to 0-1 range
    return max(0.0, min(1.0, (score + 1.0) / 2.0))
