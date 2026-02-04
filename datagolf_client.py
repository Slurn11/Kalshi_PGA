import logging
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)

LIVE_PREDS_URL = "https://feeds.datagolf.com/preds/in-play"
PRE_TOURNAMENT_URL = "https://feeds.datagolf.com/preds/pre-tournament"
BOOK_ODDS_URL = "https://feeds.datagolf.com/betting/source-matchup-odds"
SKILL_URL = "https://feeds.datagolf.com/preds/player-decompositions"

# Module-level cache so we only fetch once per cycle
_last_raw_players: list[dict] = []
_cached_book_odds: dict = {}
_cached_skill_data: dict = {}


def _fetch_raw() -> list[dict]:
    """Fetch raw player list from Data Golf and cache it."""
    global _last_raw_players
    try:
        resp = requests.get(
            LIVE_PREDS_URL,
            params={
                "tour": "pga",
                "odds_format": "percent",
                "file_format": "json",
                "key": config.DATAGOLF_API_KEY,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error(f"Data Golf fetch failed: {e}")
        _last_raw_players = []
        return []

    if not data:
        logger.info("Data Golf returned empty response (no live tournament)")
        _last_raw_players = []
        return []

    players = data if isinstance(data, list) else data.get("data", data.get("players", []))
    if not isinstance(players, list):
        logger.warning(f"Unexpected Data Golf response format: {type(data)}")
        _last_raw_players = []
        return []

    _last_raw_players = players
    return players


def get_live_probabilities() -> dict[str, dict[str, float]]:
    """Fetch live in-play probabilities from Data Golf.

    Returns dict mapping player name to probability dict:
        {"Scottie Scheffler": {"win": 25.3, "top_5": 55.1, "top_10": 72.0, ...}, ...}
    Probabilities are in percent (0-100).
    """
    players = _fetch_raw()
    if not players:
        return {}

    # Check if tournament is finished: all players in R3+ have completed R4
    weekend_players = [
        p for p in players
        if p.get("player_name") and int(p.get("round", 0) or 0) >= 3
    ]
    if weekend_players and all(
        int(p.get("round", 0) or 0) >= 4 and int(p.get("thru", 0) or 0) >= 18
        for p in weekend_players
    ):
        logger.info("Data Golf: tournament finished (all players R4 thru 18)")
        _last_raw_players = []
        return {}

    result = {}
    for p in players:
        raw_name = p.get("player_name", "").strip()
        if not raw_name:
            continue
        name = _normalize_name(raw_name)
        result[name] = {
            "win": _to_float(p.get("win", 0)) * 100,
            "top_5": _to_float(p.get("top_5", 0)) * 100,
            "top_10": _to_float(p.get("top_10", 0)) * 100,
            "top_20": _to_float(p.get("top_20", 0)) * 100,
            "make_cut": _to_float(p.get("make_cut", 0)) * 100,
        }

    logger.info(f"Data Golf: {len(result)} players with live probabilities")
    return result


def get_leaderboard() -> dict[str, dict]:
    """Build leaderboard context from the last Data Golf fetch.

    Call get_live_probabilities() first in the same cycle so _last_raw_players is populated.
    """
    result = {}
    for p in _last_raw_players:
        raw_name = p.get("player_name", "").strip()
        if not raw_name:
            continue
        name = _normalize_name(raw_name)

        pos_str = str(p.get("current_pos", "")).strip()
        try:
            position = int(pos_str.lstrip("T"))
        except (ValueError, AttributeError):
            position = 999

        thru = int(p.get("thru", 0) or 0)
        result[name] = {
            "position": position,
            "score_to_par": int(p.get("current_score", 0) or 0),
            "round_number": int(p.get("round", 1) or 1),
            "thru": thru,
            "holes_remaining": 18 - thru if thru > 0 else 18,
        }

    return result


def get_book_odds(market_type: str = "win") -> dict[str, dict[str, float]]:
    """Fetch sportsbook odds from Data Golf.

    Returns dict of {player_name: {book_name: implied_prob}} or empty dict on failure.
    Results are cached per cycle — call clear_cycle_cache() between cycles.
    """
    global _cached_book_odds
    cache_key = market_type
    if cache_key in _cached_book_odds:
        return _cached_book_odds[cache_key]

    try:
        resp = requests.get(
            BOOK_ODDS_URL,
            params={
                "tour": "pga",
                "market": market_type,
                "odds_format": "implied_prob",
                "file_format": "json",
                "key": config.DATAGOLF_API_KEY,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.debug(f"Book odds fetch failed (optional): {e}")
        _cached_book_odds[cache_key] = {}
        return {}

    result = {}
    odds_list = data if isinstance(data, list) else data.get("odds", data.get("data", []))
    if not isinstance(odds_list, list):
        _cached_book_odds[cache_key] = {}
        return {}

    for entry in odds_list:
        raw_name = entry.get("player_name", "").strip()
        if not raw_name:
            continue
        name = _normalize_name(raw_name)
        books = {}
        for key, val in entry.items():
            if key in ("player_name", "dg_id", "player_id"):
                continue
            prob = _to_float(val)
            if prob > 0:
                books[key.lower()] = prob
        if books:
            result[name] = books

    _cached_book_odds[cache_key] = result
    logger.info(f"Book odds ({market_type}): {len(result)} players from DG")
    return result


def get_player_skill_breakdown() -> dict[str, dict[str, float]]:
    """Fetch strokes gained breakdown from Data Golf.

    Returns {player_name: {sg_ott, sg_app, sg_arg, sg_putt, sg_total}} or empty dict.
    """
    global _cached_skill_data
    if _cached_skill_data:
        return _cached_skill_data

    try:
        resp = requests.get(
            SKILL_URL,
            params={
                "tour": "pga",
                "file_format": "json",
                "key": config.DATAGOLF_API_KEY,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.debug(f"Skill breakdown fetch failed (optional): {e}")
        return {}

    result = {}
    players = data if isinstance(data, list) else data.get("players", data.get("data", []))
    if not isinstance(players, list):
        return {}

    for p in players:
        raw_name = p.get("player_name", "").strip()
        if not raw_name:
            continue
        name = _normalize_name(raw_name)
        result[name] = {
            "sg_ott": _to_float(p.get("sg_ott", 0)),
            "sg_app": _to_float(p.get("sg_app", 0)),
            "sg_arg": _to_float(p.get("sg_arg", 0)),
            "sg_putt": _to_float(p.get("sg_putt", 0)),
            "sg_total": _to_float(p.get("sg_total", 0)),
        }

    _cached_skill_data = result
    logger.info(f"Skill data: {len(result)} players")
    return result


def get_pre_tournament_probabilities() -> dict[str, dict[str, float]]:
    """Fetch pre-tournament probabilities from Data Golf.

    Returns dict mapping player name to probability dict, same structure as live.
    Includes special key '_tournament_name' with the event name.
    """
    try:
        resp = requests.get(
            PRE_TOURNAMENT_URL,
            params={
                "tour": "pga",
                "odds_format": "percent",
                "file_format": "json",
                "key": config.DATAGOLF_API_KEY,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error(f"Data Golf pre-tournament fetch failed: {e}")
        return {}

    if not data:
        return {}

    # Extract tournament name if present
    tournament_name = ""
    if isinstance(data, dict):
        tournament_name = data.get("event_name", data.get("tournament", ""))
        players = data.get("data", data.get("players", data.get("baseline_history_fit", [])))
    elif isinstance(data, list):
        players = data
    else:
        return {}

    if not isinstance(players, list):
        return {}

    result = {"_tournament_name": tournament_name} if tournament_name else {}
    for p in players:
        raw_name = p.get("player_name", "").strip()
        if not raw_name:
            continue
        name = _normalize_name(raw_name)
        result[name] = {
            "win": _to_float(p.get("win", 0)) * 100,
            "top_5": _to_float(p.get("top_5", 0)) * 100,
            "top_10": _to_float(p.get("top_10", 0)) * 100,
            "top_20": _to_float(p.get("top_20", 0)) * 100,
            "make_cut": _to_float(p.get("make_cut", 0)) * 100,
        }

    logger.info(f"Data Golf: {len(result) - (1 if '_tournament_name' in result else 0)} players with pre-tournament probabilities")
    return result


def clear_cycle_cache():
    """Clear per-cycle caches. Call at the start of each polling cycle."""
    global _cached_book_odds, _cached_skill_data
    _cached_book_odds = {}
    _cached_skill_data = {}


def _normalize_name(name: str) -> str:
    """Convert 'Last, First' to 'First Last'."""
    if "," in name:
        parts = name.split(",", 1)
        return f"{parts[1].strip()} {parts[0].strip()}"
    return name


def _to_float(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0
