"""Background polling scheduler that wraps main.run_cycle()."""

import asyncio
import logging
import time

from tui.data_manager import DataManager, CycleSnapshot

logger = logging.getLogger(__name__)


async def run_polling_loop(dm: DataManager):
    """Run the main polling loop in a background thread, updating DataManager."""
    import config
    from main import run_cycle, NO_TOURNAMENT_INTERVAL, CycleResult
    from kalshi_client import KalshiClient
    from positions import get_position_stats, get_open_positions
    from database import get_accuracy_stats, get_clv_stats

    client = KalshiClient()
    loop = asyncio.get_event_loop()

    # Mark claude connected once (it's available if we got this far)
    dm.claude_connected = True

    while True:
        try:
            await dm.set_status("SCANNING")

            # Run sync cycle in thread
            cycle_result: CycleResult = await loop.run_in_executor(
                None, run_cycle, client
            )

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
            )

            await dm.update_cycle(snapshot)

            # Fetch fresh stats in thread
            pos_stats = await loop.run_in_executor(None, get_position_stats)
            clv_stats = await loop.run_in_executor(None, get_clv_stats)
            acc_stats = await loop.run_in_executor(None, get_accuracy_stats)
            open_pos = await loop.run_in_executor(None, get_open_positions)
            await dm.update_stats(pos_stats, clv_stats, acc_stats, open_pos)

            # Check telegram commands
            try:
                from telegram_commands import check_commands
                await loop.run_in_executor(None, check_commands)
            except Exception:
                pass

            # Determine sleep interval
            if not cycle_result.tournament_active:
                interval = NO_TOURNAMENT_INTERVAL
            else:
                interval = config.POLL_INTERVAL_SEC

        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)
            snapshot = CycleSnapshot(
                timestamp=time.time(),
                error=str(e),
            )
            await dm.update_cycle(snapshot)
            interval = config.POLL_INTERVAL_SEC

        await dm.set_status("WAITING" if interval > 120 else "IDLE")

        # Sleep in 1-second increments for countdown display
        for remaining in range(interval, 0, -1):
            dm.next_cycle_countdown = remaining
            await asyncio.sleep(1)
        dm.next_cycle_countdown = 0
