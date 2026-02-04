import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "decisions.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    player_name TEXT NOT NULL,
    market_ticker TEXT NOT NULL,
    market_type TEXT NOT NULL,
    dg_prob REAL NOT NULL,
    kalshi_implied_prob REAL NOT NULL,
    edge_pct REAL NOT NULL,
    leaderboard_position INTEGER,
    score_to_par INTEGER,
    round_number INTEGER,
    holes_completed INTEGER
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
    decision TEXT NOT NULL CHECK(decision IN ('BET', 'PASS', 'WATCH')),
    reasoning TEXT NOT NULL,
    confidence REAL,
    suggested_stake_pct REAL,
    timestamp REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
    result TEXT CHECK(result IN ('WIN', 'LOSS', 'PUSH', 'PENDING')),
    final_position INTEGER,
    timestamp REAL
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL UNIQUE,
    player_name TEXT NOT NULL,
    market_type TEXT NOT NULL,
    entry_price REAL NOT NULL,
    entry_edge REAL NOT NULL,
    entry_timestamp REAL NOT NULL,
    exit_price REAL,
    exit_timestamp REAL,
    profit_loss REAL,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN', 'CLOSED'))
);

CREATE TABLE IF NOT EXISTS clv_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL UNIQUE,
    player_name TEXT NOT NULL,
    market_type TEXT NOT NULL,
    entry_price REAL NOT NULL,
    closing_price REAL,
    clv_cents REAL,
    settlement_price REAL,
    outcome TEXT,
    timestamp REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS manual_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT,
    player_name TEXT NOT NULL,
    market_type TEXT NOT NULL,
    tournament_name TEXT,
    entry_price REAL NOT NULL,
    entry_timestamp REAL NOT NULL,
    exit_price REAL,
    exit_timestamp REAL,
    profit_loss REAL,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN', 'CLOSED'))
);

CREATE INDEX IF NOT EXISTS idx_opp_player ON opportunities(player_name);
CREATE INDEX IF NOT EXISTS idx_opp_market_type ON opportunities(market_type);
CREATE INDEX IF NOT EXISTS idx_decisions_decision ON decisions(decision);
CREATE INDEX IF NOT EXISTS idx_outcomes_result ON outcomes(result);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_clv_ticker ON clv_tracking(ticker);
CREATE INDEX IF NOT EXISTS idx_manual_positions_status ON manual_positions(status);
"""


def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    # Add betting_phase column if not present (idempotent)
    for table in ("opportunities", "decisions"):
        try:
            db.execute(f"ALTER TABLE {table} ADD COLUMN betting_phase TEXT")
            db.commit()
        except Exception:
            pass  # column already exists
    # Add tournament_name column to positions if not present
    try:
        db.execute("ALTER TABLE positions ADD COLUMN tournament_name TEXT")
        db.commit()
    except Exception:
        pass  # column already exists
    db.close()


def log_opportunity(
    player_name: str,
    market_ticker: str,
    market_type: str,
    dg_prob: float,
    kalshi_implied_prob: float,
    edge_pct: float,
    leaderboard_position: Optional[int] = None,
    score_to_par: Optional[int] = None,
    round_number: Optional[int] = None,
    holes_completed: Optional[int] = None,
    betting_phase: Optional[str] = None,
) -> int:
    db = get_db()
    cur = db.execute(
        """INSERT INTO opportunities
        (timestamp, player_name, market_ticker, market_type, dg_prob,
         kalshi_implied_prob, edge_pct, leaderboard_position, score_to_par,
         round_number, holes_completed, betting_phase)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (time.time(), player_name, market_ticker, market_type, dg_prob,
         kalshi_implied_prob, edge_pct, leaderboard_position, score_to_par,
         round_number, holes_completed, betting_phase),
    )
    db.commit()
    opp_id = cur.lastrowid
    db.close()
    return opp_id


def log_decision(
    opportunity_id: int,
    decision: str,
    reasoning: str,
    confidence: Optional[float] = None,
    suggested_stake_pct: Optional[float] = None,
    betting_phase: Optional[str] = None,
) -> int:
    db = get_db()
    cur = db.execute(
        """INSERT INTO decisions
        (opportunity_id, decision, reasoning, confidence, suggested_stake_pct, timestamp, betting_phase)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (opportunity_id, decision, reasoning, confidence, suggested_stake_pct, time.time(), betting_phase),
    )
    db.commit()
    dec_id = cur.lastrowid
    db.close()
    return dec_id


def log_outcome(opportunity_id: int, result: str, final_position: Optional[int] = None):
    db = get_db()
    db.execute(
        """INSERT INTO outcomes (opportunity_id, result, final_position, timestamp)
        VALUES (?, ?, ?, ?)""",
        (opportunity_id, result, final_position, time.time()),
    )
    db.commit()
    db.close()


def get_bet_history(
    market_type: Optional[str] = None,
    min_edge: Optional[float] = None,
    round_number: Optional[int] = None,
    decision: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Query past decisions with optional filters. Used by the agent."""
    db = get_db()
    query = """
        SELECT o.player_name, o.market_type, o.dg_prob, o.kalshi_implied_prob,
               o.edge_pct, o.round_number, o.leaderboard_position,
               d.decision, d.reasoning, d.confidence,
               out.result
        FROM opportunities o
        JOIN decisions d ON d.opportunity_id = o.id
        LEFT JOIN outcomes out ON out.opportunity_id = o.id
        WHERE 1=1
    """
    params = []
    if market_type:
        query += " AND o.market_type = ?"
        params.append(market_type)
    if min_edge is not None:
        query += " AND o.edge_pct >= ?"
        params.append(min_edge)
    if round_number is not None:
        query += " AND o.round_number = ?"
        params.append(round_number)
    if decision:
        query += " AND d.decision = ?"
        params.append(decision)
    query += " ORDER BY o.timestamp DESC LIMIT ?"
    params.append(limit)

    rows = db.execute(query, params).fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_accuracy_stats(
    market_type: Optional[str] = None,
    min_edge: Optional[float] = None,
) -> dict:
    """Get win/loss stats for BET decisions."""
    db = get_db()
    query = """
        SELECT out.result, COUNT(*) as cnt
        FROM opportunities o
        JOIN decisions d ON d.opportunity_id = o.id
        JOIN outcomes out ON out.opportunity_id = o.id
        WHERE d.decision = 'BET' AND out.result IN ('WIN', 'LOSS')
    """
    params = []
    if market_type:
        query += " AND o.market_type = ?"
        params.append(market_type)
    if min_edge is not None:
        query += " AND o.edge_pct >= ?"
        params.append(min_edge)
    query += " GROUP BY out.result"

    rows = db.execute(query, params).fetchall()
    db.close()

    stats = {"wins": 0, "losses": 0, "total": 0, "accuracy": 0.0}
    for r in rows:
        if r["result"] == "WIN":
            stats["wins"] = r["cnt"]
        elif r["result"] == "LOSS":
            stats["losses"] = r["cnt"]
    stats["total"] = stats["wins"] + stats["losses"]
    if stats["total"] > 0:
        stats["accuracy"] = stats["wins"] / stats["total"]
    return stats


def record_entry_for_clv(
    ticker: str, player_name: str, market_type: str, entry_price: float
):
    """Record a bet entry for CLV tracking."""
    db = get_db()
    try:
        db.execute(
            """INSERT INTO clv_tracking
            (ticker, player_name, market_type, entry_price, timestamp)
            VALUES (?, ?, ?, ?, ?)""",
            (ticker, player_name, market_type, entry_price, time.time()),
        )
        db.commit()
    except Exception:
        pass  # duplicate ticker
    finally:
        db.close()


def update_closing_price(ticker: str, closing_price: float):
    """Update closing price and calculate CLV."""
    db = get_db()
    db.execute(
        """UPDATE clv_tracking
        SET closing_price = ?, clv_cents = ? - entry_price
        WHERE ticker = ?""",
        (closing_price, closing_price, ticker),
    )
    db.commit()
    db.close()


def update_clv_outcome(ticker: str, settlement_price: float, outcome: str):
    """Update settlement and outcome for CLV record."""
    db = get_db()
    db.execute(
        """UPDATE clv_tracking
        SET settlement_price = ?, outcome = ?
        WHERE ticker = ?""",
        (settlement_price, outcome, ticker),
    )
    db.commit()
    db.close()


def get_clv_stats() -> dict:
    """Get aggregate CLV statistics."""
    db = get_db()
    row = db.execute(
        """SELECT COUNT(*) as total,
                  AVG(clv_cents) as avg_clv,
                  SUM(CASE WHEN clv_cents > 0 THEN 1 ELSE 0 END) as positive_clv,
                  SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                  AVG(CASE WHEN outcome = 'WIN' THEN clv_cents END) as avg_clv_wins,
                  AVG(CASE WHEN outcome = 'LOSS' THEN clv_cents END) as avg_clv_losses
           FROM clv_tracking
           WHERE clv_cents IS NOT NULL"""
    ).fetchone()
    db.close()

    total = row["total"] or 0
    return {
        "total_bets": total,
        "avg_clv_cents": round(row["avg_clv"] or 0, 1),
        "positive_clv_pct": round((row["positive_clv"] or 0) / total * 100, 1) if total > 0 else 0,
        "wins": row["wins"] or 0,
        "avg_clv_wins": round(row["avg_clv_wins"] or 0, 1),
        "avg_clv_losses": round(row["avg_clv_losses"] or 0, 1),
    }


def get_stats_by_phase() -> dict:
    """Get win/loss/pnl stats grouped by betting phase."""
    db = get_db()
    rows = db.execute(
        """SELECT d.betting_phase, out.result, COUNT(*) as cnt,
                  SUM(CASE WHEN p.profit_loss IS NOT NULL THEN p.profit_loss ELSE 0 END) as pnl
           FROM decisions d
           JOIN opportunities o ON o.id = d.opportunity_id
           LEFT JOIN outcomes out ON out.opportunity_id = o.id
           LEFT JOIN positions p ON p.ticker = o.market_ticker
           WHERE d.decision = 'BET' AND out.result IN ('WIN', 'LOSS')
           GROUP BY d.betting_phase, out.result"""
    ).fetchall()
    db.close()

    stats = {}
    for r in rows:
        phase = r["betting_phase"] or "UNKNOWN"
        if phase not in stats:
            stats[phase] = {"wins": 0, "losses": 0, "total": 0, "pnl": 0}
        if r["result"] == "WIN":
            stats[phase]["wins"] = r["cnt"]
        elif r["result"] == "LOSS":
            stats[phase]["losses"] = r["cnt"]
        stats[phase]["pnl"] += r["pnl"] or 0
    for phase in stats:
        stats[phase]["total"] = stats[phase]["wins"] + stats[phase]["losses"]
    return stats


# Manual position functions (user's actual bets, separate from recommendations)

def add_manual_position(
    player_name: str,
    market_type: str,
    entry_price: float,
    tournament_name: Optional[str] = None,
    ticker: Optional[str] = None,
) -> int:
    """Add a manually entered bet position. Returns the position ID."""
    db = get_db()
    cur = db.execute(
        """INSERT INTO manual_positions
        (ticker, player_name, market_type, tournament_name, entry_price, entry_timestamp, status)
        VALUES (?, ?, ?, ?, ?, ?, 'OPEN')""",
        (ticker, player_name, market_type, tournament_name, entry_price, time.time()),
    )
    db.commit()
    pos_id = cur.lastrowid
    db.close()
    return pos_id


def close_manual_position(position_id: int, won: bool):
    """Close a manual position with win/loss outcome."""
    db = get_db()
    row = db.execute(
        "SELECT entry_price FROM manual_positions WHERE id = ? AND status = 'OPEN'",
        (position_id,),
    ).fetchone()
    if not row:
        db.close()
        return
    entry_price = row["entry_price"]
    exit_price = 100.0 if won else 0.0
    profit_loss = exit_price - entry_price
    db.execute(
        """UPDATE manual_positions
        SET exit_price = ?, exit_timestamp = ?, profit_loss = ?, status = 'CLOSED'
        WHERE id = ?""",
        (exit_price, time.time(), profit_loss, position_id),
    )
    db.commit()
    db.close()


def close_manual_position_by_ticker(ticker: str, exit_price: float):
    """Close a manual position by ticker with the given exit price."""
    db = get_db()
    now = time.time()
    db.execute(
        """UPDATE manual_positions
        SET exit_price = ?, exit_timestamp = ?,
            profit_loss = ? - entry_price,
            status = 'CLOSED'
        WHERE ticker = ? AND status = 'OPEN'""",
        (exit_price, now, exit_price, ticker),
    )
    db.commit()
    db.close()


def get_open_manual_positions() -> list[dict]:
    """Return all open manual positions."""
    db = get_db()
    rows = db.execute("SELECT * FROM manual_positions WHERE status = 'OPEN'").fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_manual_position_stats() -> dict:
    """Aggregate stats for manual positions."""
    db = get_db()
    open_count = db.execute(
        "SELECT COUNT(*) FROM manual_positions WHERE status = 'OPEN'"
    ).fetchone()[0]
    closed = db.execute(
        """SELECT COUNT(*) as cnt,
                  SUM(profit_loss) as total_pnl,
                  SUM(CASE WHEN profit_loss > 0 THEN 1 ELSE 0 END) as wins
           FROM manual_positions WHERE status = 'CLOSED'"""
    ).fetchone()
    closed_count = closed["cnt"] or 0
    total_pnl = closed["total_pnl"] or 0.0
    wins = closed["wins"] or 0
    db.close()
    return {
        "open_count": open_count,
        "closed_count": closed_count,
        "total_realized_pnl": total_pnl,
        "win_rate": wins / closed_count if closed_count > 0 else 0.0,
        "wins": wins,
        "losses": closed_count - wins,
    }


def get_recommendation_stats() -> dict:
    """Calculate win rate for all BET recommendations (from decisions/outcomes tables)."""
    db = get_db()
    row = db.execute(
        """SELECT
               COUNT(*) as total,
               SUM(CASE WHEN out.result = 'WIN' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN out.result = 'LOSS' THEN 1 ELSE 0 END) as losses
           FROM decisions d
           JOIN opportunities o ON o.id = d.opportunity_id
           LEFT JOIN outcomes out ON out.opportunity_id = o.id
           WHERE d.decision = 'BET'"""
    ).fetchone()
    db.close()
    total = row["total"] or 0
    wins = row["wins"] or 0
    losses = row["losses"] or 0
    settled = wins + losses
    return {
        "total_recommendations": total,
        "settled": settled,
        "wins": wins,
        "losses": losses,
        "win_rate": wins / settled if settled > 0 else 0.0,
    }


# Initialize on import
init_db()
