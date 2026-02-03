"""Multi-book edge validation for betting opportunities."""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class EdgeValidation:
    edge_vs_kalshi: float
    edge_vs_pinnacle: Optional[float]
    edge_vs_consensus: Optional[float]
    confidence: str  # "high", "medium", "low"
    pinnacle_implied: Optional[float]
    consensus_implied: Optional[float]
    books_available: int


def validate_edge(
    player_name: str,
    market_type: str,
    dg_prob: float,
    kalshi_implied: float,
    book_odds: dict[str, float],
) -> EdgeValidation:
    """Validate edge against multiple books.

    Args:
        player_name: Golfer name.
        market_type: Market type (winner, top5, etc.).
        dg_prob: Data Golf model probability (0-1).
        kalshi_implied: Kalshi implied probability (0-1).
        book_odds: Dict of {book_name: implied_probability} from DG.

    Returns:
        EdgeValidation with confidence level.
    """
    edge_vs_kalshi = (dg_prob - kalshi_implied) * 100

    pinnacle_implied = book_odds.get("pinnacle")
    edge_vs_pinnacle = None
    if pinnacle_implied is not None:
        edge_vs_pinnacle = (dg_prob - pinnacle_implied) * 100

    # Consensus = average of all available books
    consensus_implied = None
    edge_vs_consensus = None
    if book_odds:
        vals = [v for v in book_odds.values() if v is not None and v > 0]
        if vals:
            consensus_implied = sum(vals) / len(vals)
            edge_vs_consensus = (dg_prob - consensus_implied) * 100

    # Determine confidence
    books_available = len(book_odds)

    if books_available == 0:
        confidence = "medium"
    elif edge_vs_pinnacle is not None and edge_vs_pinnacle >= 3 and edge_vs_kalshi >= 8:
        confidence = "high"
    elif edge_vs_pinnacle is not None and edge_vs_pinnacle < 0:
        confidence = "low"
    elif edge_vs_consensus is not None and edge_vs_consensus < 0:
        confidence = "low"
    else:
        confidence = "medium"

    return EdgeValidation(
        edge_vs_kalshi=edge_vs_kalshi,
        edge_vs_pinnacle=edge_vs_pinnacle,
        edge_vs_consensus=edge_vs_consensus,
        confidence=confidence,
        pinnacle_implied=pinnacle_implied,
        consensus_implied=consensus_implied,
        books_available=books_available,
    )
