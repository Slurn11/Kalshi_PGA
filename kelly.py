"""Kelly criterion stake sizing for Kalshi betting."""


def kelly_stake(
    probability: float,
    price_cents: int,
    kelly_fraction: float = 0.25,
    max_stake_pct: float = 0.05,
) -> float:
    """Calculate Kelly stake as fraction of bankroll.

    Args:
        probability: Model probability of winning (0-1).
        price_cents: Kalshi yes_ask price in cents (1-99).
        kelly_fraction: Fraction of full Kelly to use (default quarter Kelly).
        max_stake_pct: Hard cap on stake as fraction of bankroll.

    Returns:
        Stake as fraction of bankroll (0.0 to max_stake_pct).
    """
    if price_cents <= 0 or price_cents >= 100 or probability <= 0 or probability >= 1:
        return 0.0

    price = price_cents / 100.0
    # Kelly formula: f* = (bp - q) / b
    # where b = (1 - price) / price (net odds), p = probability, q = 1 - p
    b = (1 - price) / price
    q = 1 - probability
    f_star = (b * probability - q) / b

    if f_star <= 0:
        return 0.0

    stake = f_star * kelly_fraction
    return min(stake, max_stake_pct)


def kelly_edge_required(price_cents: int) -> float:
    """Return breakeven probability for a given price."""
    if price_cents <= 0 or price_cents >= 100:
        return 0.0
    return price_cents / 100.0


def format_stake_recommendation(
    probability: float,
    price_cents: int,
    bankroll: float = 1000.0,
) -> dict:
    """Full Kelly recommendation with context.

    Returns:
        Dict with stake_pct, stake_dollars, breakeven_prob,
        edge_over_breakeven, is_positive_ev.
    """
    breakeven = kelly_edge_required(price_cents)
    edge_over_breakeven = (probability - breakeven) * 100
    stake_pct = kelly_stake(probability, price_cents)
    stake_dollars = stake_pct * bankroll

    return {
        "stake_pct": round(stake_pct * 100, 2),  # as percentage
        "stake_dollars": round(stake_dollars, 2),
        "breakeven_prob": round(breakeven * 100, 1),
        "edge_over_breakeven": round(edge_over_breakeven, 1),
        "is_positive_ev": edge_over_breakeven > 0,
    }
