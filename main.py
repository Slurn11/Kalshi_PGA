import difflib
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import config
import database
from agent import evaluate_opportunity
from alerts import send_recommendation, send_sell_alert
from bet_logger import log_recommendation
from positions import open_position, get_open_positions, close_position, check_exit_conditions
from datagolf_client import get_live_probabilities, get_leaderboard, get_book_odds, get_player_skill_breakdown, clear_cycle_cache
from kalshi_client import KalshiClient
from telegram_commands import check_commands
from kelly import kelly_stake, format_stake_recommendation
from edge_validator import validate_edge
from edge_adjustments import get_min_edge_for_round

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

NO_TOURNAMENT_INTERVAL = 3600  # 1 hour when no live tournament
MIN_EDGE_TO_EVALUATE = 8.0  # Don't waste API calls on tiny edges
MAX_SPREAD = 15  # Skip markets with bid/ask spread > 15¢


@dataclass
class CycleResult:
    """Structured result from a single polling cycle."""
    timestamp: float = 0.0
    tournament_active: bool = False
    markets_found: int = 0
    players_loaded: int = 0
    round_num: int = 0
    min_edge: float = 0.0
    evaluations: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    alerts_sent: int = 0
    positions_checked: int = 0
    leaderboard: dict = field(default_factory=dict)
    error: Optional[str] = None

    def __int__(self):
        """Backward compat: int(result) returns alerts_sent."""
        return self.alerts_sent

    def __eq__(self, other):
        """Backward compat: result == -1 checks."""
        if isinstance(other, int):
            if not self.tournament_active and other == -1:
                return True
            return self.alerts_sent == other
        return NotImplemented


def match_name(name: str, names: list[str]) -> Optional[str]:
    matches = difflib.get_close_matches(name, names, n=1, cutoff=0.6)
    return matches[0] if matches else None


MARKET_TYPE_TO_DG_KEY = {
    "winner": "win",
    "top5": "top_5",
    "top10": "top_10",
    "top20": "top_20",
    "make_cut": "make_cut",
}


def run_cycle(client: KalshiClient) -> CycleResult:
    """Run one poll cycle. Returns CycleResult with full cycle data."""
    result = CycleResult(timestamp=time.time())
    clear_cycle_cache()

    # 1. Fetch Data Golf probabilities
    logger.info("Fetching Data Golf live probabilities...")
    dg_probs = get_live_probabilities()
    if not dg_probs:
        logger.info("No live Data Golf data (tournament may not be active)")
        result.tournament_active = False
        return result

    result.tournament_active = True
    result.players_loaded = len(dg_probs)
    logger.info(f"Data Golf: {len(dg_probs)} players")

    # 2. Fetch Kalshi markets
    logger.info("Discovering Kalshi golf markets...")
    markets = client.discover_golf_markets()
    if not markets:
        logger.info("No Kalshi golf markets found")
        return result

    result.markets_found = len(markets)
    logger.info(f"Found {len(markets)} Kalshi golf markets")

    # 3. Build leaderboard from Data Golf data (already fetched above)
    leaderboard = get_leaderboard()
    result.leaderboard = leaderboard
    logger.info(f"Leaderboard: {len(leaderboard)} golfers")

    # 4. Find opportunities and evaluate with agent
    dg_names = list(dg_probs.keys())

    # Determine round number from leaderboard for edge adjustments
    round_num = 3  # default
    if leaderboard:
        rounds = [v.get("round_number", 3) for v in leaderboard.values()]
        if rounds:
            round_num = max(set(rounds), key=rounds.count)  # mode

    result.round_num = round_num
    min_edge = get_min_edge_for_round(MIN_EDGE_TO_EVALUATE, round_num)
    result.min_edge = min_edge
    logger.info(f"Round {round_num}: min edge threshold = {min_edge:.1f}%")

    # Fetch optional data sources
    skill_data = get_player_skill_breakdown()

    for market in markets:
        # Match player name to Data Golf
        dg_match = match_name(market.golfer_name, dg_names)
        if not dg_match:
            continue

        dg_key = MARKET_TYPE_TO_DG_KEY.get(market.market_type)
        if not dg_key:
            continue

        dg_prob_pct = dg_probs[dg_match].get(dg_key, 0)
        if dg_prob_pct <= 0:
            continue

        dg_prob = dg_prob_pct / 100.0
        impl_prob = market.implied_probability
        if impl_prob <= 0:
            continue

        edge_pct = (dg_prob - impl_prob) * 100

        # Round-adjusted edge threshold
        if edge_pct < min_edge:
            if edge_pct > 0:
                logger.info(
                    f"Skipping {dg_match} {market.market_type}: "
                    f"Edge too low ({edge_pct:+.1f}% < {min_edge:.1f}% threshold)"
                )
                result.skipped.append({
                    "player": dg_match, "type": market.market_type,
                    "reason": "edge_too_low", "edge": edge_pct,
                })
            continue

        spread = market.yes_ask - market.yes_bid
        if spread > MAX_SPREAD:
            logger.info(
                f"Skipping {dg_match} {market.market_type}: "
                f"Spread too wide ({spread}¢, ask={market.yes_ask}¢, bid={market.yes_bid}¢)"
            )
            result.skipped.append({
                "player": dg_match, "type": market.market_type,
                "reason": "spread_too_wide", "spread": spread,
            })
            continue

        # Get leaderboard context
        lb_match = match_name(dg_match, list(leaderboard.keys()))
        lb_context = leaderboard.get(lb_match) if lb_match else None

        # Sanity check: if player is well inside threshold late in tournament,
        # a low ask price likely indicates a stale/mispriced order
        if lb_context and lb_context.get("round_number", 1) >= 3:
            pos = lb_context.get("position", 999)
            thresholds = {"top5": 5, "top10": 10, "top20": 20}
            threshold = thresholds.get(market.market_type)
            if threshold and pos <= threshold and market.yes_ask < 70:
                logger.warning(
                    f"Skipping {dg_match} {market.market_type}: "
                    f"Likely stale price — player at T{pos} in R{lb_context['round_number']} "
                    f"but ask only {market.yes_ask}¢"
                )
                result.skipped.append({
                    "player": dg_match, "type": market.market_type,
                    "reason": "stale_price",
                })
                continue

        # Fetch book odds and validate edge (optional)
        dg_market_key = dg_key.replace("_", "")  # top_5 -> top5
        book_odds_all = get_book_odds(dg_market_key)
        player_book_odds = book_odds_all.get(dg_match, {})
        validation = validate_edge(
            dg_match, market.market_type, dg_prob, impl_prob, player_book_odds
        )
        validation_dict = {
            "confidence": validation.confidence,
            "edge_vs_kalshi": validation.edge_vs_kalshi,
            "edge_vs_pinnacle": validation.edge_vs_pinnacle,
            "edge_vs_consensus": validation.edge_vs_consensus,
            "books_available": validation.books_available,
        }

        # Kelly stake calculation
        kelly_rec = format_stake_recommendation(dg_prob, market.yes_ask)

        # Player skill data (optional)
        player_skill = skill_data.get(dg_match)

        # Log opportunity
        opp_id = database.log_opportunity(
            player_name=dg_match,
            market_ticker=market.ticker,
            market_type=market.market_type,
            dg_prob=dg_prob,
            kalshi_implied_prob=impl_prob,
            edge_pct=edge_pct,
            leaderboard_position=lb_context.get("position") if lb_context else None,
            score_to_par=lb_context.get("score_to_par") if lb_context else None,
            round_number=lb_context.get("round_number") if lb_context else None,
            holes_completed=lb_context.get("thru") if lb_context else None,
        )

        # Agent evaluation
        logger.info(
            f"Evaluating: {dg_match} {market.market_type} "
            f"DG={dg_prob:.0%} ask={market.yes_ask}¢ bid={market.yes_bid}¢ edge={edge_pct:+.1f}% "
            f"validation={validation.confidence}"
        )
        eval_result = evaluate_opportunity(
            player_name=dg_match,
            market_type=market.market_type,
            market_ticker=market.ticker,
            dg_prob=dg_prob,
            kalshi_implied_prob=impl_prob,
            edge_pct=edge_pct,
            leaderboard_context=lb_context,
            edge_validation=validation_dict,
            kelly_rec=kelly_rec,
            skill_data=player_skill,
        )

        # Log decision
        database.log_decision(
            opportunity_id=opp_id,
            decision=eval_result["decision"],
            reasoning=eval_result["reasoning"],
            confidence=eval_result.get("confidence"),
            suggested_stake_pct=eval_result.get("suggested_stake_pct"),
        )

        logger.info(f"Agent decision: {eval_result['decision']} — {eval_result['reasoning'][:100]}")

        # Track evaluation in cycle result
        result.evaluations.append({
            "player": dg_match,
            "type": market.market_type,
            "ticker": market.ticker,
            "dg_prob": dg_prob,
            "implied_prob": impl_prob,
            "edge": edge_pct,
            "ask": market.yes_ask,
            "bid": market.yes_bid,
            "spread": market.yes_ask - market.yes_bid,
            "decision": eval_result["decision"],
            "confidence": eval_result.get("confidence", 0),
            "reasoning": eval_result.get("reasoning", ""),
            "validation": validation_dict.get("confidence", ""),
        })

        # Log all decisions to Excel
        log_recommendation(
            player_name=dg_match,
            market_type=market.market_type,
            market_ticker=market.ticker,
            dg_prob=dg_prob,
            kalshi_implied_prob=impl_prob,
            edge_pct=edge_pct,
            decision=eval_result["decision"],
            confidence=eval_result.get("confidence", 0),
            suggested_stake_pct=eval_result.get("suggested_stake_pct", 0),
            reasoning=eval_result.get("reasoning", ""),
            leaderboard_context=lb_context,
        )

        # Only alert on BET decisions
        if eval_result["decision"] == "BET":
            sent = send_recommendation(
                player_name=dg_match,
                market_type=market.market_type,
                market_ticker=market.ticker,
                dg_prob=dg_prob,
                kalshi_implied_prob=impl_prob,
                edge_pct=edge_pct,
                decision=eval_result["decision"],
                reasoning=eval_result["reasoning"],
                confidence=eval_result["confidence"],
                suggested_stake_pct=eval_result["suggested_stake_pct"],
                leaderboard_context=lb_context,
                yes_ask=market.yes_ask,
                yes_bid=market.yes_bid,
                edge_validation=validation_dict,
                kelly_rec=kelly_rec,
                skill_data=player_skill,
            )
            if sent:
                result.alerts_sent += 1
                open_position(
                    ticker=market.ticker,
                    player_name=dg_match,
                    market_type=market.market_type,
                    entry_price=market.yes_ask,
                    entry_edge=edge_pct,
                )
                database.record_entry_for_clv(
                    market.ticker, dg_match, market.market_type, market.yes_ask
                )

    # 5. Check open positions for exit conditions
    positions = get_open_positions()
    result.positions_checked = len(positions)
    _check_positions(client, markets, dg_probs)

    return result


def _check_positions(
    client: KalshiClient,
    markets: list,
    dg_probs: dict,
):
    """Check all open positions for exit conditions using already-fetched data."""
    positions = get_open_positions()
    if not positions:
        return

    # Build ticker -> market lookup from already-fetched markets
    market_by_ticker = {m.ticker: m for m in markets}
    dg_names = list(dg_probs.keys())

    for pos in positions:
        ticker = pos["ticker"]
        market = market_by_ticker.get(ticker)

        # Only check early exits for outright winner markets
        if pos["market_type"] != "winner":
            continue

        if market:
            # Calculate current edge
            dg_match = match_name(pos["player_name"], dg_names)
            current_edge = 0.0
            if dg_match:
                dg_key = MARKET_TYPE_TO_DG_KEY.get(pos["market_type"])
                if dg_key:
                    dg_prob_pct = dg_probs[dg_match].get(dg_key, 0)
                    impl_prob = market.implied_probability
                    if impl_prob > 0:
                        current_edge = (dg_prob_pct / 100.0 - impl_prob) * 100

            should_exit, reason = check_exit_conditions(
                ticker, market.yes_bid, current_edge
            )
            if should_exit:
                send_sell_alert(
                    player_name=pos["player_name"],
                    market_type=pos["market_type"],
                    entry_price=pos["entry_price"],
                    exit_price=market.yes_bid,
                    reason=reason,
                )
                close_position(ticker, market.yes_bid)
        else:
            # Market no longer in active list — check if settled
            try:
                data = client._request("GET", f"/markets/{ticker}")
                m = data.get("market", data)
                status = m.get("status", "")
                if status in ("settled", "finalized", "closed"):
                    result = m.get("result", "")
                    exit_price = 100.0 if result == "yes" else 0.0
                    close_position(ticker, exit_price)
                    logger.info(
                        f"Position {ticker} settled: result={result}, exit={exit_price}¢"
                    )
            except Exception as e:
                logger.debug(f"Could not check settled market {ticker}: {e}")


def main():
    logger.info("Starting Kalshi PGA Golf Agent System")
    client = KalshiClient()

    while True:
        try:
            check_commands()
        except Exception as e:
            logger.error(f"Telegram command error: {e}")

        try:
            cycle = run_cycle(client)
            if not cycle.tournament_active:
                interval = NO_TOURNAMENT_INTERVAL
                logger.info(f"No live tournament, sleeping {interval}s...")
            else:
                if cycle.alerts_sent > 0:
                    logger.info(f"Sent {cycle.alerts_sent} alert(s)")
                interval = config.POLL_INTERVAL_SEC
        except KeyboardInterrupt:
            logger.info("Shutting down")
            break
        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)
            interval = config.POLL_INTERVAL_SEC

        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Shutting down")
            break


if __name__ == "__main__":
    main()
