import logging

import requests

import config
from positions import get_open_positions, get_position_stats
from database import get_clv_stats
from kelly import format_stake_recommendation

logger = logging.getLogger(__name__)

_last_update_id = 0


def check_commands():
    """Poll Telegram for incoming commands."""
    global _last_update_id

    if not config.TELEGRAM_BOT_TOKEN:
        return

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"offset": _last_update_id + 1, "timeout": 0}

    try:
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code != 200:
            return
        data = resp.json()
    except Exception:
        return

    for update in data.get("result", []):
        _last_update_id = update["update_id"]

        message = update.get("message", {})
        text = message.get("text", "").strip().lower()
        chat_id = str(message.get("chat", {}).get("id", ""))

        if chat_id != config.TELEGRAM_CHAT_ID:
            continue

        if text == "/positions":
            _send_positions()
        elif text == "/stats":
            _send_stats()
        elif text == "/clv":
            _send_clv()
        elif text.startswith("/kelly"):
            _send_kelly(text)


def _reply(message: str):
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }, timeout=10)


def _send_positions():
    positions = get_open_positions()

    if not positions:
        _reply("📊 <b>Open Positions (0)</b>\n\nNo open positions.")
        return

    lines = [f"📊 <b>Open Positions ({len(positions)}):</b>", ""]
    for p in positions:
        player = p["player_name"]
        mtype = p["market_type"].upper()
        entry = p["entry_price"]
        edge = p["entry_edge"]
        lines.append(f"{player} {mtype}: {entry:.0f}¢ entry (+{edge:.0f}¢ edge)")

    _reply("\n".join(lines))


def _send_stats():
    stats = get_position_stats()

    open_count = stats["open_count"]
    closed_count = stats["closed_count"]
    win_rate = stats["win_rate"]
    total_pnl = stats["total_realized_pnl"]
    avg_hold_min = stats["avg_hold_time_minutes"]

    # Format hold time
    if avg_hold_min >= 60:
        hold_str = f"{avg_hold_min / 60:.1f} hrs"
    else:
        hold_str = f"{avg_hold_min:.0f} min"

    wins = round(win_rate * closed_count)

    lines = [
        "📈 <b>Golf Position Stats</b>",
        "",
        f"Open: {open_count} | Closed: {closed_count}",
    ]

    if closed_count > 0:
        lines.append(f"Win Rate: {win_rate:.0%} ({wins}/{closed_count})")
        lines.append(f"Total P/L: {total_pnl:+.0f}¢")
        lines.append(f"Avg Hold: {hold_str}")
    else:
        lines.append("No closed positions yet.")

    _reply("\n".join(lines))


def _send_clv():
    stats = get_clv_stats()

    if stats["total_bets"] == 0:
        _reply("📉 <b>CLV Stats</b>\n\nNo CLV data yet.")
        return

    lines = [
        "📉 <b>Closing Line Value (CLV)</b>",
        "",
        f"Total bets tracked: {stats['total_bets']}",
        f"Avg CLV: {stats['avg_clv_cents']:+.1f}¢",
        f"Positive CLV rate: {stats['positive_clv_pct']:.0f}%",
        f"Wins: {stats['wins']}",
        f"Avg CLV (wins): {stats['avg_clv_wins']:+.1f}¢",
        f"Avg CLV (losses): {stats['avg_clv_losses']:+.1f}¢",
    ]
    _reply("\n".join(lines))


def _send_kelly(text: str):
    parts = text.strip().split()
    if len(parts) != 3:
        _reply("Usage: /kelly &lt;prob%&gt; &lt;price_cents&gt;\nExample: /kelly 35 28")
        return

    try:
        prob_pct = float(parts[1])
        price = int(parts[2])
    except ValueError:
        _reply("Usage: /kelly &lt;prob%&gt; &lt;price_cents&gt;\nExample: /kelly 35 28")
        return

    if prob_pct <= 0 or prob_pct >= 100 or price <= 0 or price >= 100:
        _reply("Probability must be 1-99% and price must be 1-99¢")
        return

    rec = format_stake_recommendation(prob_pct / 100.0, price)

    lines = [
        "🧮 <b>Kelly Calculator</b>",
        "",
        f"Model prob: {prob_pct:.0f}% | Price: {price}¢",
        f"Breakeven: {rec['breakeven_prob']:.0f}%",
        f"Edge over breakeven: {rec['edge_over_breakeven']:+.1f}%",
        f"Positive EV: {'✅' if rec['is_positive_ev'] else '❌'}",
        f"Quarter-Kelly stake: {rec['stake_pct']:.2f}% (${rec['stake_dollars']:.2f} on $1000)",
    ]
    _reply("\n".join(lines))
