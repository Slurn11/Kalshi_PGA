from dataclasses import dataclass


@dataclass
class KalshiMarket:
    ticker: str
    golfer_name: str
    market_type: str  # "winner", "top5", "top10", "top20", "make_cut"
    yes_ask: float  # Current yes ask price (0-100 cents)
    yes_bid: float
    no_ask: float
    no_bid: float

    @property
    def implied_probability(self) -> float:
        return self.yes_ask / 100.0
