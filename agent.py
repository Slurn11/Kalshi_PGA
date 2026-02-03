import json
import logging
from typing import Optional

import requests

import config
import database

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = """You are a sharp sports betting analyst specializing in PGA golf markets on Kalshi.

You receive betting opportunities where Data Golf's live predictive model disagrees with Kalshi's market-implied probability. Your job is to evaluate each opportunity and decide: BET, PASS, or WATCH.

Consider:
- The numerical edge (Data Golf prob vs Kalshi implied prob)
- Tournament context: what round, how many holes remain, leaderboard position
- Model confidence: Data Golf is more reliable late in tournaments when positions are settled
- Market efficiency: Kalshi golf markets can be thin, especially on weekends — thin markets misprice more often
- Historical base rates: how often do golfers in position X actually finish top Y?
- Your own track record: you'll be given your past accuracy stats

Be decisive. A 10% edge in round 4 with 9 holes left is much more actionable than a 15% edge in round 1.

You MUST respond with valid JSON in this exact format:
{
    "decision": "BET" | "PASS" | "WATCH",
    "confidence": 0.0-1.0,
    "suggested_stake_pct": 0.0-5.0,
    "reasoning": "2-4 sentence explanation"
}"""


def evaluate_opportunity(
    player_name: str,
    market_type: str,
    market_ticker: str,
    dg_prob: float,
    kalshi_implied_prob: float,
    edge_pct: float,
    leaderboard_context: Optional[dict] = None,
    edge_validation: Optional[dict] = None,
    kelly_rec: Optional[dict] = None,
    skill_data: Optional[dict] = None,
) -> dict:
    """Use Claude to evaluate a betting opportunity.

    Args:
        player_name: Golfer name.
        market_type: "winner", "top5", "top10", "top20".
        market_ticker: Kalshi market ticker.
        dg_prob: Data Golf probability (0-1 scale).
        kalshi_implied_prob: Kalshi implied probability (0-1 scale).
        edge_pct: (dg_prob - kalshi_implied_prob) * 100.
        leaderboard_context: Optional dict with position, score_to_par, round, holes_completed.
        edge_validation: Optional dict with confidence, edge_vs_pinnacle, etc.
        kelly_rec: Optional dict from format_stake_recommendation().
        skill_data: Optional dict with strokes gained breakdown.

    Returns:
        Dict with decision, confidence, suggested_stake_pct, reasoning.
    """
    # Get historical stats for context
    overall_stats = database.get_accuracy_stats()
    type_stats = database.get_accuracy_stats(market_type=market_type)
    edge_stats = database.get_accuracy_stats(min_edge=10.0)

    # Get recent decisions for this market type
    recent = database.get_bet_history(market_type=market_type, decision="BET", limit=10)

    # Build the prompt
    user_message = f"""Evaluate this betting opportunity:

**Player:** {player_name}
**Market:** {market_type.upper()} ({market_ticker})
**Data Golf Probability:** {dg_prob:.1%}
**Kalshi Implied Probability:** {kalshi_implied_prob:.1%}
**Edge:** {edge_pct:+.1f}%
"""

    if leaderboard_context:
        ctx = leaderboard_context
        user_message += f"""
**Leaderboard Context:**
- Position: {ctx.get('position', 'N/A')}
- Score to Par: {ctx.get('score_to_par', 'N/A')}
- Round: {ctx.get('round_number', 'N/A')}
- Through: {ctx.get('thru', 'N/A')} holes (of 18)
- Holes Remaining in Round: {ctx.get('holes_remaining', 'N/A')}
"""

    user_message += f"""
**Your Track Record:**
- Overall: {overall_stats['wins']}/{overall_stats['total']} ({overall_stats['accuracy']:.0%} accuracy)
- {market_type.upper()} bets: {type_stats['wins']}/{type_stats['total']} ({type_stats['accuracy']:.0%})
- 10%+ edge bets: {edge_stats['wins']}/{edge_stats['total']} ({edge_stats['accuracy']:.0%})
"""

    if edge_validation:
        conf_emoji = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(
            edge_validation.get("confidence", "medium"), "🟡"
        )
        user_message += f"""
**Edge Validation:** {conf_emoji} {edge_validation.get('confidence', 'N/A').upper()} confidence
- Edge vs Kalshi: {edge_validation.get('edge_vs_kalshi', 0):+.1f}%"""
        if edge_validation.get("edge_vs_pinnacle") is not None:
            user_message += f"\n- Edge vs Pinnacle: {edge_validation['edge_vs_pinnacle']:+.1f}%"
        if edge_validation.get("edge_vs_consensus") is not None:
            user_message += f"\n- Edge vs Consensus: {edge_validation['edge_vs_consensus']:+.1f}%"
        user_message += f"\n- Books checked: {edge_validation.get('books_available', 0)}\n"

    if kelly_rec:
        user_message += f"""
**Kelly Criterion:**
- Recommended stake: {kelly_rec.get('stake_pct', 0):.2f}% of bankroll
- Breakeven prob: {kelly_rec.get('breakeven_prob', 0):.1f}%
- Edge over breakeven: {kelly_rec.get('edge_over_breakeven', 0):+.1f}%
- Positive EV: {'Yes' if kelly_rec.get('is_positive_ev') else 'No'}
"""

    if skill_data:
        user_message += f"""
**Strokes Gained (SG:OTT most predictive, SG:PUTT least):**
- SG:OTT (off tee): {skill_data.get('sg_ott', 0):+.2f}
- SG:APP (approach): {skill_data.get('sg_app', 0):+.2f}
- SG:ARG (around green): {skill_data.get('sg_arg', 0):+.2f}
- SG:PUTT: {skill_data.get('sg_putt', 0):+.2f}
- SG:Total: {skill_data.get('sg_total', 0):+.2f}
"""

    if recent:
        user_message += "\n**Recent BET decisions on this market type:**\n"
        for r in recent[:5]:
            result = r.get("result") or "PENDING"
            user_message += (
                f"- {r['player_name']}: edge {r['edge_pct']:+.1f}%, "
                f"result: {result}\n"
            )

    # Call Anthropic API
    try:
        resp = requests.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": config.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 300,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_message}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error(f"Anthropic API call failed: {e}")
        return _fallback_decision(edge_pct)

    # Parse response
    try:
        text = data["content"][0]["text"]
        # Extract JSON from response (handle markdown code blocks)
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text.strip())

        # Validate
        assert result["decision"] in ("BET", "PASS", "WATCH")
        result["confidence"] = float(result.get("confidence", 0.5))
        # Use Kelly stake if available, otherwise use Claude's suggestion
        if kelly_rec and kelly_rec.get("is_positive_ev"):
            result["suggested_stake_pct"] = kelly_rec["stake_pct"]
        else:
            result["suggested_stake_pct"] = float(result.get("suggested_stake_pct", 0))
        return result
    except (json.JSONDecodeError, KeyError, AssertionError) as e:
        logger.warning(f"Failed to parse agent response: {e}, raw: {text[:200]}")
        return _fallback_decision(edge_pct)


def _fallback_decision(edge_pct: float) -> dict:
    """Simple fallback if the API call fails."""
    if abs(edge_pct) >= 15:
        return {
            "decision": "BET",
            "confidence": 0.5,
            "suggested_stake_pct": 1.0,
            "reasoning": f"Fallback: {edge_pct:+.1f}% edge exceeds 15% threshold. Agent API unavailable.",
        }
    return {
        "decision": "WATCH",
        "confidence": 0.3,
        "suggested_stake_pct": 0,
        "reasoning": f"Fallback: {edge_pct:+.1f}% edge. Agent API unavailable, defaulting to WATCH.",
    }
