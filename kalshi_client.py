import base64
import re
import time
from typing import Optional

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

import config
from models import KalshiMarket


class KalshiClient:
    def __init__(self):
        self.api_key = config.KALSHI_API_KEY
        self.base_url = config.KALSHI_BASE_URL
        self.session = requests.Session()
        self._private_key = None

    @property
    def private_key(self):
        if self._private_key is None:
            with open(config.KALSHI_RSA_PRIVATE_KEY_PATH, "rb") as f:
                self._private_key = serialization.load_pem_private_key(f.read(), password=None)
        return self._private_key

    def _sign_request(self, method: str, path: str, timestamp_ms: str) -> str:
        """Create RSA-PSS signature for Kalshi API authentication."""
        message = f"{timestamp_ms}{method}{path}"
        signature = self.private_key.sign(
            message.encode("utf-8"),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")

    def _request(self, method: str, path: str, params: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        timestamp_ms = str(int(time.time() * 1000))
        signature = self._sign_request(method.upper(), path, timestamp_ms)

        headers = {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "Content-Type": "application/json",
        }

        resp = self.session.request(method, url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    GOLF_SERIES = ["KXPGATOUR", "KXPGA", "KXPGATOP5", "KXPGATOP10", "KXPGATOP20", "KXPGACUT"]

    def discover_golf_markets(self) -> list[KalshiMarket]:
        """Find open PGA golf markets on Kalshi via series tickers."""
        import logging
        _log = logging.getLogger(__name__)
        markets = []

        for series in self.GOLF_SERIES:
            data = None
            for attempt in range(3):
                try:
                    data = self._request("GET", "/events", params={
                        "series_ticker": series,
                        "with_nested_markets": "true",
                        "status": "open",
                        "limit": 100,
                    })
                    break
                except requests.exceptions.HTTPError as e:
                    if e.response is not None and e.response.status_code == 429:
                        wait = 2 ** attempt
                        _log.warning(f"Rate limited on {series}, retrying in {wait}s...")
                        time.sleep(wait)
                    else:
                        _log.error(f"Failed to fetch {series}: {e}")
                        break
                except Exception as e:
                    _log.error(f"Failed to fetch {series}: {e}")
                    break

            if not data:
                continue

            for event in data.get("events", []):
                for m in event.get("markets", []):
                    if m.get("status") not in ("open", "active"):
                        continue

                    # Skip markets with no ask price (completely illiquid)
                    if not m.get("yes_ask"):
                        continue

                    golfer_name, market_type = self._parse_market(m)
                    if not golfer_name:
                        continue

                    markets.append(KalshiMarket(
                        ticker=m["ticker"],
                        golfer_name=golfer_name,
                        market_type=market_type,
                        yes_ask=m.get("yes_ask", 0),
                        yes_bid=m.get("yes_bid", 0),
                        no_ask=m.get("no_ask", 0),
                        no_bid=m.get("no_bid", 0),
                    ))

            time.sleep(0.5)

        return markets

    def _parse_market(self, market: dict) -> tuple[str, str]:
        """Extract golfer name and market type from market data."""
        title = market.get("title", "")
        subtitle = market.get("subtitle", "")
        combined = f"{title} {subtitle}"

        # Exclude FRL (first round leader) markets
        lower = combined.lower()
        if "round leader" in lower:
            return "", "unknown"

        # Determine market type from series ticker or title
        market_type = "winner"
        event_ticker = (market.get("event_ticker") or "").upper()
        if "TOP5" in event_ticker or "top 5" in lower or "top five" in lower:
            market_type = "top5"
        elif "TOP10" in event_ticker or "top 10" in lower or "top ten" in lower:
            market_type = "top10"
        elif "TOP20" in event_ticker or "top 20" in lower or "top twenty" in lower:
            market_type = "top20"
        elif "PGACUT" in event_ticker or "make the cut" in lower or "make cut" in lower:
            market_type = "make_cut"

        # Try to extract golfer name - look for "Will X win/finish"
        patterns = [
            r"(?:Will\s+)(.+?)(?:\s+(?:win|finish|place|make))",
            r"(.+?)(?:\s+(?:to win|to finish|to place))",
        ]
        for pat in patterns:
            match = re.search(pat, title, re.IGNORECASE)
            if match:
                return match.group(1).strip(), market_type

        # Fallback: use subtitle as golfer name if it looks like a name
        if subtitle and len(subtitle.split()) <= 4:
            return subtitle.strip(), market_type

        return "", market_type

    def get_orderbook(self, ticker: str) -> dict:
        """Get current orderbook for a market."""
        return self._request("GET", f"/markets/{ticker}/orderbook")

    def refresh_market_prices(self, market: KalshiMarket) -> KalshiMarket:
        """Update a market's prices from the live orderbook.

        Orderbook format:
        {
          "orderbook": {
            "yes": [[price, quantity], ...],  # Bids to BUY yes
            "no": [[price, quantity], ...]    # Bids to BUY no
          }
        }

        To get YES ask price: Find best NO bid, then yes_ask = 100 - best_no_bid
        To get YES bid price: Find best YES bid directly
        """
        book = self.get_orderbook(market.ticker)
        ob = book.get("orderbook", {})

        # Handle None values (API returns None instead of empty list when no orders)
        yes_bids = ob.get("yes") or []  # People wanting to BUY yes
        no_bids = ob.get("no") or []    # People wanting to BUY no

        # YES ask = 100 - best NO bid (to buy YES, you sell to the NO bidder)
        if no_bids:
            best_no_bid = max(b[0] for b in no_bids)
            market.yes_ask = 100 - best_no_bid

        # YES bid = best YES bid (to sell YES, hit the YES bidder)
        if yes_bids:
            market.yes_bid = max(b[0] for b in yes_bids)

        # NO ask = 100 - best YES bid (to buy NO, you sell to the YES bidder)
        if yes_bids:
            best_yes_bid = max(b[0] for b in yes_bids)
            market.no_ask = 100 - best_yes_bid

        # NO bid = best NO bid
        if no_bids:
            market.no_bid = max(b[0] for b in no_bids)

        return market
