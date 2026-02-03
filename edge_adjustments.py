"""Round-based edge weighting for golf betting."""

# Multipliers: later rounds = more predictable = lower edge required
_ROUND_MULTIPLIERS = {
    1: 0.70,
    2: 0.85,
    3: 1.00,
    4: 1.15,
}

_CONFIDENCE_ADJUSTMENTS = {
    1: -0.10,
    2: -0.05,
    3: 0.00,
    4: 0.10,
}


def get_min_edge_for_round(base_min_edge: float, round_num: int) -> float:
    """Return adjusted minimum edge threshold for the given round.

    Later rounds require less raw edge because model predictions are more reliable.

    Args:
        base_min_edge: Base minimum edge (e.g. 8.0).
        round_num: Tournament round (1-4).

    Returns:
        Adjusted minimum edge threshold.
    """
    multiplier = _ROUND_MULTIPLIERS.get(round_num, 1.0)
    return base_min_edge / multiplier


def adjust_confidence_for_round(confidence: float, round_num: int) -> float:
    """Adjust agent confidence based on round predictability.

    Args:
        confidence: Raw confidence (0-1).
        round_num: Tournament round (1-4).

    Returns:
        Adjusted confidence, clamped to [0, 1].
    """
    adj = _CONFIDENCE_ADJUSTMENTS.get(round_num, 0.0)
    return max(0.0, min(1.0, confidence + adj))
