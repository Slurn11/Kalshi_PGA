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

    GOLF_SERIES = ["KXPGATOUR", "KXPGA", "KXPGATOP5", "KXPGATOP10", "KXPGATOP20"]

    def discover_golf_markets(self) -> list[KalshiMarket]:
        """Find open PGA golf markets on Kalshi via series tickers."""
        markets = []

        for series in self.GOLF_SERIES:
            try:
                data = self._request("GET", "/events", params={
                    "series_ticker": series,
                    "with_nested_markets": "true",
                    "status": "open",
                    "limit": 100,
                })
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Failed to fetch {series}: {e}")
                continue

            for event in data.get("events", []):
                for m in event.get("markets", []):
                    if m.get("status") not in ("open", "active"):
                        continue

                    # Skip markets with no liquidity (no yes bid = can't exit position)
                    if not m.get("yes_bid"):
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

            time.sleep(0.2)

        return markets

    def _parse_market(self, market: dict) -> tuple[str, str]:
        """Extract golfer name and market type from market data."""
        title = market.get("title", "")
        subtitle = market.get("subtitle", "")
        combined = f"{title} {subtitle}"

        # Determine market type from series ticker or title
        market_type = "winner"
        event_ticker = (market.get("event_ticker") or "").upper()
        lower = combined.lower()
        if "TOP5" in event_ticker or "top 5" in lower or "top five" in lower:
            market_type = "top5"
        elif "TOP10" in event_ticker or "top 10" in lower or "top ten" in lower:
            market_type = "top10"
        elif "TOP20" in event_ticker or "top 20" in lower or "top twenty" in lower:
            market_type = "top20"

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
        """Update a market's prices from the orderbook."""
        book = self.get_orderbook(market.ticker)
        yes_asks = book.get("yes", [])
        no_asks = book.get("no", [])

        if yes_asks:
            market.yes_ask = min(a[0] for a in yes_asks)
        if no_asks:
            market.no_ask = min(a[0] for a in no_asks)

        return market
