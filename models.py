import time
from dataclasses import dataclass, field


@dataclass
class ScanStage:
    """Represents a single stage in the scan pipeline."""
    name: str       # "fetch_dg", "discover_markets", "match_players", etc.
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class KalshiMarket:
    ticker: str
    golfer_name: str
    market_type: str  # "winner", "top5", "top10", "top20", "make_cut"
    yes_ask: float  # Current yes ask price (0-100 cents)
    yes_bid: float
    no_ask: float
    no_bid: float
    verified: bool = False  # True if prices confirmed from live orderbook

    @property
    def implied_probability(self) -> float:
        return self.yes_ask / 100.0
