"""Background polling scheduler that wraps main.run_cycle()."""

import asyncio
import functools
import logging
import time

from tui.data_manager import DataManager, CycleSnapshot

logger = logging.getLogger(__name__)


async def run_polling_loop(dm: DataManager):
    """Run the main polling loop in a background thread, updating DataManager."""
    import config
    from main import run_cycle, CycleResult
    from kalshi_client import KalshiClient
    from positions import get_position_stats, get_open_positions, settle_open_manual_positions
    from database import get_accuracy_stats, get_clv_stats, get_stats_by_phase, get_manual_position_stats, get_recommendation_stats
    from tournament_state import detect_phase, get_poll_interval, TournamentPhase

    client = KalshiClient()
    loop = asyncio.get_event_loop()

    # Mark claude connected once (it's available if we got this far)
    dm.claude_connected = True

    # Track phase across cycles (avoid extra API calls for detection)
    current_phase = TournamentPhase.IDLE

    while True:
        try:
            await dm.set_status("SCANNING")
            dm.clear_stage_log()

            # Create stage callback that bridges sync -> async
            def stage_callback(stage):
                loop.call_soon_threadsafe(
                    asyncio.ensure_future,
                    dm.push_stage(stage),
                )

            # Run sync cycle in thread with stage callback
            cycle_result: CycleResult = await loop.run_in_executor(
                None, functools.partial(
                    run_cycle, client,
                    on_stage=stage_callback,
                    betting_phase=current_phase.value,
                )
            )

            # Detect phase from cycle result (no extra API calls)
            if cycle_result.tournament_active:
                if cycle_result.players_loaded > 0 and cycle_result.round_num == 0:
                    current_phase = TournamentPhase.PRE_TOURNAMENT
                elif cycle_result.round_num > 0:
                    current_phase = TournamentPhase.LIVE_ROUND
            else:
                # Check if pre-tournament data was used (players loaded but no tournament_active
                # means run_cycle got pre-tournament data but no markets or no edges)
                if cycle_result.players_loaded > 0:
                    current_phase = TournamentPhase.PRE_TOURNAMENT
                else:
                    current_phase = TournamentPhase.IDLE

            dm.phase = current_phase.value
            # Extract tournament name
            if cycle_result.tournament_name:
                dm.tournament_name = cycle_result.tournament_name
            elif cycle_result.leaderboard:
                dm.tournament_name = dm.tournament_name or "PGA Tournament"

            # Convert to snapshot
            snapshot = CycleSnapshot(
                timestamp=cycle_result.timestamp,
                tournament_active=cycle_result.tournament_active,
                markets_found=cycle_result.markets_found,
                players_loaded=cycle_result.players_loaded,
                round_num=cycle_result.round_num,
                min_edge=cycle_result.min_edge,
                evaluations=cycle_result.evaluations,
                skipped=cycle_result.skipped,
                alerts_sent=cycle_result.alerts_sent,
                positions_checked=cycle_result.positions_checked,
                leaderboard=cycle_result.leaderboard,
                tournament_name=cycle_result.tournament_name,
                top_edges=cycle_result.top_edges,
            )

            await dm.update_cycle(snapshot)

            # Settle open manual positions (auto-close settled markets)
            await loop.run_in_executor(
                None, lambda: settle_open_manual_positions(client)
            )

            # Fetch fresh stats in thread
            pos_stats = await loop.run_in_executor(None, get_position_stats)
            clv_stats = await loop.run_in_executor(None, get_clv_stats)
            acc_stats = await loop.run_in_executor(None, get_accuracy_stats)
            open_pos = await loop.run_in_executor(None, get_open_positions)
            phase_stats = await loop.run_in_executor(None, get_stats_by_phase)
            manual_stats = await loop.run_in_executor(None, get_manual_position_stats)
            rec_stats = await loop.run_in_executor(None, get_recommendation_stats)
            await dm.update_stats(pos_stats, clv_stats, acc_stats, open_pos)
            dm.phase_stats = phase_stats
            dm.manual_stats = manual_stats
            dm.recommendation_stats = rec_stats

            # Check telegram commands
            try:
                from telegram_commands import check_commands
                await loop.run_in_executor(None, check_commands)
            except Exception:
                pass

            # Use phase-aware interval
            interval = get_poll_interval(current_phase)
            dm.poll_interval = interval

        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)
            snapshot = CycleSnapshot(
                timestamp=time.time(),
                error=str(e),
            )
            await dm.update_cycle(snapshot)
            interval = config.POLL_INTERVAL_LIVE_SEC

        await dm.set_status("WAITING" if interval > 120 else "IDLE")

        # Interruptible countdown sleep
        dm.force_scan.clear()
        for remaining in range(interval, 0, -1):
            dm.next_cycle_countdown = remaining
            try:
                await asyncio.wait_for(dm.force_scan.wait(), timeout=1.0)
                dm.force_scan.clear()
                break  # interrupted — scan now
            except asyncio.TimeoutError:
                pass
        dm.next_cycle_countdown = 0
