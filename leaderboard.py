import logging

import requests

logger = logging.getLogger(__name__)

ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard"


def get_leaderboard() -> dict[str, dict]:
    """Fetch current PGA leaderboard from ESPN. Returns {player_name: context_dict}."""
    try:
        resp = requests.get(ESPN_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"ESPN fetch failed: {e}")
        return {}

    result = {}
    events = data.get("events", [])
    if not events:
        return {}

    for competitor in events[0].get("competitions", [{}])[0].get("competitors", []):
        athlete = competitor.get("athlete", {})
        name = athlete.get("displayName", "")
        if not name:
            continue

        status = competitor.get("status", {})
        pos_text = status.get("position", {}).get("displayName", "")
        position = _parse_position(pos_text)

        score_str = competitor.get("score", "E")
        score_to_par = int(score_str) if score_str not in ("E", "", None) else 0

        # Linescores are the most reliable round indicator.
        # Each entry = one round. value > 0 means that round is complete.
        # A 0.0 entry means the round exists but hasn't been completed yet.
        linescores = competitor.get("linescores", [])
        completed_rounds = sum(1 for ls in linescores if ls.get("value", 0) > 0)
        total_rounds_listed = len(linescores)

        # Determine current round and holes played in it
        thru_raw = status.get("thru")
        period_raw = status.get("period")

        if thru_raw is not None:
            # ESPN is reporting live mid-round data
            if isinstance(thru_raw, str):
                thru = 18 if thru_raw == "F" else (int(thru_raw) if thru_raw.isdigit() else 0)
            else:
                thru = int(thru_raw) if thru_raw else 0
            current_round = int(period_raw) if period_raw else completed_rounds + 1
            holes_completed = (current_round - 1) * 18 + thru
        else:
            # ESPN not reporting live thru (between sessions / no active play)
            # Use linescores: if there's an incomplete round (0.0), they're in it
            if total_rounds_listed > completed_rounds:
                # There's a round slot with 0 — that's the upcoming/current round
                current_round = completed_rounds + 1
            else:
                # All listed rounds complete (or no rounds at all)
                current_round = completed_rounds if completed_rounds > 0 else 1
            holes_completed = completed_rounds * 18

        result[name] = {
            "position": position,
            "score_to_par": score_to_par,
            "round_number": current_round,
            "holes_completed": holes_completed,
        }

    logger.info(f"ESPN leaderboard: {len(result)} golfers")
    return result


def _parse_position(pos_str: str) -> int:
    if not pos_str:
        return 999
    pos_str = pos_str.strip().upper()
    if pos_str in ("CUT", "WD", "DQ", "MDF"):
        return 999
    pos_str = pos_str.lstrip("T")
    try:
        return int(pos_str)
    except ValueError:
        return 999
