import logging
import time

from database import get_db

logger = logging.getLogger(__name__)


def open_position(
    ticker: str,
    player_name: str,
    market_type: str,
    entry_price: float,
    entry_edge: float,
    tournament_name: str = None,
) -> bool:
    """Open a new position. Returns False if ticker already has an OPEN position."""
    db = get_db()
    try:
        db.execute(
            """INSERT INTO positions
            (ticker, player_name, market_type, entry_price, entry_edge, entry_timestamp, status, tournament_name)
            VALUES (?, ?, ?, ?, ?, ?, 'OPEN', ?)""",
            (ticker, player_name, market_type, entry_price, entry_edge, time.time(), tournament_name),
        )
        db.commit()
        logger.info(f"Opened position: {player_name} {market_type} @ {entry_price}¢")
        return True
    except Exception as e:
        # UNIQUE constraint on ticker means duplicate
        logger.debug(f"Position already open for {ticker}: {e}")
        return False
    finally:
        db.close()


def close_position(ticker: str, exit_price: float):
    """Close an open position with the given exit price."""
    db = get_db()
    now = time.time()
    db.execute(
        """UPDATE positions
        SET exit_price = ?, exit_timestamp = ?,
            profit_loss = ? - entry_price,
            status = 'CLOSED'
        WHERE ticker = ? AND status = 'OPEN'""",
        (exit_price, now, exit_price, ticker),
    )
    db.commit()
    db.close()
    logger.info(f"Closed position {ticker} @ {exit_price}¢")


def get_open_positions() -> list[dict]:
    """Return all open positions."""
    db = get_db()
    rows = db.execute("SELECT * FROM positions WHERE status = 'OPEN'").fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_position_stats() -> dict:
    """Aggregate stats across all positions."""
    db = get_db()

    open_count = db.execute(
        "SELECT COUNT(*) FROM positions WHERE status = 'OPEN'"
    ).fetchone()[0]

    closed = db.execute(
        """SELECT COUNT(*) as cnt,
                  SUM(profit_loss) as total_pnl,
                  SUM(CASE WHEN profit_loss > 0 THEN 1 ELSE 0 END) as wins,
                  AVG((exit_timestamp - entry_timestamp) / 60.0) as avg_hold_min
           FROM positions WHERE status = 'CLOSED'"""
    ).fetchone()

    closed_count = closed["cnt"] or 0
    total_pnl = closed["total_pnl"] or 0.0
    wins = closed["wins"] or 0
    avg_hold = closed["avg_hold_min"] or 0.0

    db.close()
    return {
        "open_count": open_count,
        "closed_count": closed_count,
        "total_realized_pnl": total_pnl,
        "win_rate": wins / closed_count if closed_count > 0 else 0.0,
        "avg_hold_time_minutes": avg_hold,
    }


def check_exit_conditions(
    ticker: str, current_yes_bid: float, current_edge: float
) -> tuple[bool, str]:
    """Check if a position should be exited. Returns (should_exit, reason)."""
    db = get_db()
    row = db.execute(
        "SELECT entry_price FROM positions WHERE ticker = ? AND status = 'OPEN'",
        (ticker,),
    ).fetchone()
    db.close()

    if not row:
        return False, ""

    entry_price = row["entry_price"]

    # Profit target: +15¢
    if current_yes_bid >= entry_price + 15:
        return True, f"Profit target (+15¢)"

    # Edge flipped negative
    if current_edge <= -8:
        return True, f"Edge flipped to {current_edge:+.1f}%"

    return False, ""


def settle_open_positions(client) -> dict:
    """Query Kalshi API for each open position and settle if market closed.

    Args:
        client: KalshiClient instance.

    Returns:
        dict with {settled: int, still_open: int, errors: list}
    """
    positions = get_open_positions()
    result = {"settled": 0, "still_open": 0, "errors": []}

    for pos in positions:
        ticker = pos["ticker"]
        try:
            data = client._request("GET", f"/markets/{ticker}")
            market = data.get("market", data)
            status = market.get("status", "")
            if status in ("settled", "finalized", "closed"):
                market_result = market.get("result", "")
                exit_price = 100.0 if market_result == "yes" else 0.0
                close_position(ticker, exit_price)
                logger.info(
                    f"Settled position {pos['player_name']} {pos['market_type']}: "
                    f"result={market_result}, exit={exit_price}¢"
                )
                result["settled"] += 1
            else:
                result["still_open"] += 1
        except Exception as e:
            logger.debug(f"Could not check market {ticker}: {e}")
            result["errors"].append({"ticker": ticker, "error": str(e)})
            result["still_open"] += 1

    return result


def settle_open_manual_positions(client) -> dict:
    """Query Kalshi API for each open manual position and settle if market closed.

    Args:
        client: KalshiClient instance.

    Returns:
        dict with {settled: int, still_open: int, skipped: int, errors: list}
    """
    from database import get_open_manual_positions, close_manual_position_by_ticker

    positions = get_open_manual_positions()
    result = {"settled": 0, "still_open": 0, "skipped": 0, "errors": []}

    for pos in positions:
        ticker = pos.get("ticker")
        if not ticker:
            # No ticker - can't auto-settle
            result["skipped"] += 1
            continue

        try:
            data = client._request("GET", f"/markets/{ticker}")
            market = data.get("market", data)
            status = market.get("status", "")
            if status in ("settled", "finalized", "closed"):
                market_result = market.get("result", "")
                exit_price = 100.0 if market_result == "yes" else 0.0
                close_manual_position_by_ticker(ticker, exit_price)
                logger.info(
                    f"Settled manual position {pos['player_name']} {pos['market_type']}: "
                    f"result={market_result}, exit={exit_price}¢"
                )
                result["settled"] += 1
            else:
                result["still_open"] += 1
        except Exception as e:
            logger.debug(f"Could not check market {ticker}: {e}")
            result["errors"].append({"ticker": ticker, "error": str(e)})
            result["still_open"] += 1

    return result
