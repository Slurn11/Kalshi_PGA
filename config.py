import os
from dotenv import load_dotenv

load_dotenv()

KALSHI_API_KEY = os.getenv("KALSHI_API_KEY", "")
KALSHI_RSA_PRIVATE_KEY_PATH = os.getenv("KALSHI_RSA_PRIVATE_KEY_PATH", "")
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DATAGOLF_API_KEY = os.getenv("DATAGOLF_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

EDGE_THRESHOLD_PCT = float(os.getenv("EDGE_THRESHOLD_PCT", "8"))
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "30"))
ALERT_COOLDOWN_MIN = int(os.getenv("ALERT_COOLDOWN_MIN", "30"))
BANKROLL = float(os.getenv("BANKROLL", "100"))

# Kelly criterion
KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", "0.25"))
MAX_BET_PCT = float(os.getenv("MAX_BET_PCT", "0.05"))

# Market filters
MAX_SPREAD_CENTS = int(os.getenv("MAX_SPREAD_CENTS", "15"))

# Stale price detection
STALE_PRICE_THRESHOLD = int(os.getenv("STALE_PRICE_THRESHOLD", "70"))

# Tournament detection
NO_TOURNAMENT_INTERVAL_SEC = int(os.getenv("NO_TOURNAMENT_INTERVAL_SEC", "300"))

# Phase-specific poll intervals
POLL_INTERVAL_LIVE_SEC = int(os.getenv("POLL_INTERVAL_LIVE_SEC", "30"))
POLL_INTERVAL_PRE_TOURNAMENT_SEC = int(os.getenv("POLL_INTERVAL_PRE_TOURNAMENT_SEC", "1800"))
POLL_INTERVAL_BETWEEN_ROUNDS_SEC = int(os.getenv("POLL_INTERVAL_BETWEEN_ROUNDS_SEC", "1800"))
POLL_INTERVAL_IDLE_SEC = int(os.getenv("POLL_INTERVAL_IDLE_SEC", "3600"))

# Validation confidence filter
SKIP_LOW_CONFIDENCE = os.getenv("SKIP_LOW_CONFIDENCE", "false").lower() == "true"

# Major tournaments (prioritize these over regular events)
MAJOR_TOURNAMENTS = {
    "Masters", "The Masters", "Masters Tournament",
    "U.S. Open", "US Open",
    "The Open", "The Open Championship", "British Open",
    "PGA Championship",
}


def is_major(tournament_name: str) -> bool:
    """Check if tournament name matches a major."""
    if not tournament_name:
        return False
    name_lower = tournament_name.lower()
    return any(major.lower() in name_lower for major in MAJOR_TOURNAMENTS)
