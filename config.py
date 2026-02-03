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

EDGE_THRESHOLD_PCT = float(os.getenv("EDGE_THRESHOLD_PCT", "10"))
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "30"))
ALERT_COOLDOWN_MIN = int(os.getenv("ALERT_COOLDOWN_MIN", "30"))
