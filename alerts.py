import logging
from datetime import datetime

import requests

import config

logger = logging.getLogger(__name__)

_alert_cooldowns: dict[str, datetime] = {}


def send_telegram(message: str) -> bool:
    """Send message via Telegram bot."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured")
        logger.info(f"ALERT:\n{message}")
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("Telegram alert sent")
            return True
        else:
            logger.error(f"Telegram failed: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False


def send_alert(ticker: str, message: str) -> bool:
    """Send alert with per-market cooldown."""
    now = datetime.now()

    if ticker in _alert_cooldowns:
        elapsed = (now - _alert_cooldowns[ticker]).total_seconds() / 60
        if elapsed < config.ALERT_COOLDOWN_MIN:
            logger.debug(f"Cooldown active for {ticker}")
            return False

    success = send_telegram(message)
    if success:
        _alert_cooldowns[ticker] = now
    return success


def send_recommendation(
    player_name: str,
    market_type: str,
    market_ticker: str,
    dg_prob: float,
    kalshi_implied_prob: float,
    edge_pct: float,
    decision: str,
    reasoning: str,
    confidence: float,
    suggested_stake_pct: float,
    leaderboard_context: dict = None,
    yes_ask: int = None,
    yes_bid: int = None,
    edge_validation: dict = None,
    kelly_rec: dict = None,
    skill_data: dict = None,
) -> bool:
    """Format and send a Golf recommendation via Telegram."""
    from bet_logger import get_historical_stats

    stats = get_historical_stats(market_type)

    lines = [
        f"<b>🎯 {decision} RECOMMENDATION</b>",
        f"<b>{player_name} {market_type.upper()}</b>",
        "",
        f"Data Golf: <code>{dg_prob:.0%}</code> | Kalshi: <code>{yes_ask}¢ ask ({yes_bid}¢ bid)</code> | Spread: <code>{yes_ask - yes_bid}¢</code>" if yes_ask is not None and yes_bid is not None else f"Data Golf: <code>{dg_prob:.0%}</code> | Kalshi: <code>{kalshi_implied_prob:.0%}</code>",
        f"Edge: <code>{edge_pct:+.1f}%</code> | Confidence: <code>{confidence:.0%}</code>",
    ]

    # Edge validation confidence
    if edge_validation:
        conf_emoji = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(
            edge_validation.get("confidence", "medium"), "🟡"
        )
        ev_line = f"Validation: {conf_emoji} {edge_validation.get('confidence', '').upper()}"
        if edge_validation.get("edge_vs_pinnacle") is not None:
            ev_line += f" | vs Pinnacle: <code>{edge_validation['edge_vs_pinnacle']:+.1f}%</code>"
        lines.append(ev_line)

    # Kelly stake
    if kelly_rec:
        lines.append(
            f"Kelly Stake: <code>{kelly_rec.get('stake_pct', 0):.2f}%</code> of bankroll "
            f"| Edge over breakeven: <code>{kelly_rec.get('edge_over_breakeven', 0):+.1f}%</code>"
        )
    else:
        lines.append(f"Stake: <code>{suggested_stake_pct:.1f}%</code> of bankroll")

    if leaderboard_context:
        ctx = leaderboard_context
        pos = ctx.get("position", "?")
        stp = ctx.get("score_to_par", 0)
        rnd = ctx.get("round_number", "?")
        thru = ctx.get("thru", "?")
        remaining = ctx.get("holes_remaining", "?")
        lines.append(f"\nPosition: {pos} | Score: {stp:+d} | R{rnd} thru {thru} ({remaining} remaining)")

    if skill_data:
        lines.append(
            f"\nSG: OTT <code>{skill_data.get('sg_ott', 0):+.1f}</code> | "
            f"APP <code>{skill_data.get('sg_app', 0):+.1f}</code> | "
            f"ARG <code>{skill_data.get('sg_arg', 0):+.1f}</code> | "
            f"Putt <code>{skill_data.get('sg_putt', 0):+.1f}</code>"
        )

    lines.append("")
    lines.append("<b>📊 History</b>")
    if stats["type_total"] > 0:
        lines.append(
            f"{market_type.upper()}: {stats['type_wins']}/{stats['type_total']} "
            f"({stats['type_winrate']:.0%}) | ${stats['type_pnl']:+.0f}"
        )
    else:
        lines.append(f"{market_type.upper()}: No data yet")

    if stats["all_total"] > 0:
        lines.append(
            f"All Bets: {stats['all_wins']}/{stats['all_total']} "
            f"({stats['all_winrate']:.0%}) | ${stats['all_pnl']:+.0f}"
        )
    else:
        lines.append("All Bets: No data yet")

    lines.extend(["", f"<b>💭 Reasoning</b>", reasoning])
    lines.append("")
    now = datetime.now().strftime("%H:%M:%S")
    price_line = f"⏱ Alert generated: {now}"
    if yes_ask is not None and yes_bid is not None:
        price_line += f" | Price at detection: ask={yes_ask}¢ bid={yes_bid}¢"
    lines.append(f"<i>{price_line}</i>")
    message = "\n".join(lines)

    return send_alert(market_ticker, message)


def send_sell_alert(
    player_name: str,
    market_type: str,
    entry_price: float,
    exit_price: float,
    reason: str,
) -> bool:
    """Send a sell/exit alert. No cooldown (one-time event)."""
    pnl = exit_price - entry_price
    sign = "+" if pnl >= 0 else ""
    lines = [
        f"<b>💰 SELL: {player_name} {market_type.upper()}</b>",
        f"Entry: {entry_price:.0f}¢ → Exit: {exit_price:.0f}¢ ({sign}{pnl:.0f}¢)",
        f"Reason: {reason}",
    ]
    message = "\n".join(lines)
    return send_telegram(message)
