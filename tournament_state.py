"""Tournament phase detection and poll interval management."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import config


class TournamentPhase(Enum):
    PRE_TOURNAMENT = "PRE_TOURNAMENT"
    LIVE_ROUND = "LIVE_ROUND"
    BETWEEN_ROUNDS = "BETWEEN_ROUNDS"
    FINISHED = "FINISHED"
    IDLE = "IDLE"


@dataclass
class TournamentState:
    phase: TournamentPhase
    tournament_name: str = ""
    round_num: int = 0


def detect_phase(
    dg_live_data: dict,
    dg_pre_data: Optional[dict],
    leaderboard: dict,
) -> TournamentState:
    """Detect current tournament phase from available data.

    Args:
        dg_live_data: Live probabilities dict (player -> probs), may be empty.
        dg_pre_data: Pre-tournament probabilities dict, may be None.
        leaderboard: Leaderboard dict (player -> {position, thru, round_number, ...}).

    Returns:
        TournamentState with detected phase, tournament name, and round number.
    """
    tournament_name = ""

    # Extract tournament name from pre-tournament data if available
    if isinstance(dg_pre_data, dict) and dg_pre_data.get("_tournament_name"):
        tournament_name = dg_pre_data["_tournament_name"]

    if dg_live_data and leaderboard:
        # Check round numbers and thru counts
        rounds = [v.get("round_number", 0) for v in leaderboard.values()]
        thrus = [v.get("thru", 0) for v in leaderboard.values()]
        round_num = max(set(rounds), key=rounds.count) if rounds else 0

        # All R4 thru 18 → FINISHED
        if round_num >= 4 and all(
            v.get("round_number", 0) >= 4 and v.get("thru", 0) >= 18
            for v in leaderboard.values()
            if v.get("round_number", 0) >= 3
        ):
            return TournamentState(
                phase=TournamentPhase.FINISHED,
                tournament_name=tournament_name,
                round_num=round_num,
            )

        # Players with nonzero probs and thru > 0 → LIVE_ROUND
        has_active = any(v.get("thru", 0) > 0 and v.get("thru", 0) < 18 for v in leaderboard.values())
        if has_active:
            return TournamentState(
                phase=TournamentPhase.LIVE_ROUND,
                tournament_name=tournament_name,
                round_num=round_num,
            )

        # All thru == 18 for current round → BETWEEN_ROUNDS
        current_round_players = [
            v for v in leaderboard.values()
            if v.get("round_number", 0) == round_num
        ]
        if current_round_players and all(v.get("thru", 0) >= 18 for v in current_round_players):
            return TournamentState(
                phase=TournamentPhase.BETWEEN_ROUNDS,
                tournament_name=tournament_name,
                round_num=round_num,
            )

        # Has live data but can't determine sub-state → LIVE_ROUND
        return TournamentState(
            phase=TournamentPhase.LIVE_ROUND,
            tournament_name=tournament_name,
            round_num=round_num,
        )

    # No live data but pre-tournament data available
    if dg_pre_data and len(dg_pre_data) > 1:  # >1 to exclude _tournament_name key
        return TournamentState(
            phase=TournamentPhase.PRE_TOURNAMENT,
            tournament_name=tournament_name,
            round_num=0,
        )

    return TournamentState(
        phase=TournamentPhase.IDLE,
        tournament_name=tournament_name,
        round_num=0,
    )


def get_poll_interval(phase: TournamentPhase) -> int:
    """Return the appropriate poll interval for a given phase."""
    return {
        TournamentPhase.LIVE_ROUND: config.POLL_INTERVAL_LIVE_SEC,
        TournamentPhase.PRE_TOURNAMENT: config.POLL_INTERVAL_PRE_TOURNAMENT_SEC,
        TournamentPhase.BETWEEN_ROUNDS: config.POLL_INTERVAL_BETWEEN_ROUNDS_SEC,
        TournamentPhase.FINISHED: config.POLL_INTERVAL_IDLE_SEC,
        TournamentPhase.IDLE: config.POLL_INTERVAL_IDLE_SEC,
    }.get(phase, config.POLL_INTERVAL_IDLE_SEC)
