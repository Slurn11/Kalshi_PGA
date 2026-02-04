"""Shared state between the background poller and the TUI widgets."""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from models import ScanStage

# Load defaults from config at module level
try:
    import config as _cfg
    _DEFAULT_POLL = _cfg.POLL_INTERVAL_SEC
    _DEFAULT_COOLDOWN = _cfg.ALERT_COOLDOWN_MIN
except Exception:
    _DEFAULT_POLL = 30
    _DEFAULT_COOLDOWN = 30

try:
    from main import MIN_EDGE_TO_EVALUATE, MAX_SPREAD
except Exception:
    MIN_EDGE_TO_EVALUATE = 8.0
    MAX_SPREAD = 15


@dataclass
class CycleSnapshot:
    """A snapshot of data from one polling cycle."""
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
    tournament_name: str = ""
    error: Optional[str] = None
    top_edges: list = field(default_factory=list)  # All verified positive edges for display


class DataManager:
    """Thread-safe shared state for the TUI."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self.current_cycle: Optional[CycleSnapshot] = None
        self.cycle_count: int = 0
        self.start_time: float = time.time()
        self.eval_log: list[dict] = []
        self.status: str = "STARTING"  # STARTING, SCANNING, IDLE, WAITING, ERROR
        self.last_error: Optional[str] = None
        self.position_stats: dict = {}
        self.clv_stats: dict = {}
        self.accuracy_stats: dict = {}
        self.open_positions: list = []
        self.total_alerts_sent: int = 0
        self.last_alert_info: Optional[dict] = None  # {player, type, time}
        # Connection status
        self.dg_connected: bool = False
        self.kalshi_connected: bool = False
        self.claude_connected: bool = False
        # Config defaults
        self.poll_interval: int = _DEFAULT_POLL
        self.alert_cooldown: int = _DEFAULT_COOLDOWN
        self.base_min_edge: float = MIN_EDGE_TO_EVALUATE
        self.max_spread: int = MAX_SPREAD
        # Countdown
        self.next_cycle_countdown: int = 0
        # Phase tracking
        self.phase: str = "IDLE"
        self.tournament_name: str = ""
        # Stage log for pipeline visibility
        self.stage_log: list[ScanStage] = []
        # Force scan event
        self.force_scan: asyncio.Event = asyncio.Event()
        # Phase stats
        self.phase_stats: dict = {}
        # Manual position stats
        self.manual_stats: dict = {}
        # Recommendation stats
        self.recommendation_stats: dict = {}
        # Notify callback
        self._on_update = None
        self._on_stage = None

    def set_update_callback(self, callback):
        self._on_update = callback

    def set_stage_callback(self, callback):
        self._on_stage = callback

    def clear_stage_log(self):
        self.stage_log = []

    async def push_stage(self, stage: ScanStage):
        async with self._lock:
            self.stage_log.append(stage)
        if self._on_stage:
            self._on_stage(stage)

    async def update_cycle(self, snapshot: CycleSnapshot):
        async with self._lock:
            self.current_cycle = snapshot
            self.cycle_count += 1
            if snapshot.error:
                self.status = "ERROR"
                self.last_error = snapshot.error
            elif snapshot.tournament_active:
                self.status = "IDLE"
            else:
                self.status = "WAITING"
            # Connection status
            self.dg_connected = snapshot.players_loaded > 0
            self.kalshi_connected = snapshot.markets_found > 0
            # Track alerts
            self.total_alerts_sent += snapshot.alerts_sent
            if snapshot.alerts_sent > 0:
                for ev in reversed(snapshot.evaluations):
                    if ev.get("decision") == "BET":
                        self.last_alert_info = {
                            "player": ev["player"],
                            "type": ev["type"],
                            "time": time.time(),
                        }
                        break
            # Trim eval log
            if len(self.eval_log) > 100:
                self.eval_log = self.eval_log[-100:]
        if self._on_update:
            self._on_update()

    async def set_status(self, status: str):
        async with self._lock:
            self.status = status
        if self._on_update:
            self._on_update()

    async def update_stats(self, position_stats, clv_stats, accuracy_stats, open_positions):
        async with self._lock:
            self.position_stats = position_stats
            self.clv_stats = clv_stats
            self.accuracy_stats = accuracy_stats
            self.open_positions = open_positions

    @property
    def uptime_str(self) -> str:
        elapsed = int(time.time() - self.start_time)
        hours, rem = divmod(elapsed, 3600)
        mins, secs = divmod(rem, 60)
        if hours:
            return f"{hours}:{mins:02d}:{secs:02d}"
        return f"{mins}:{secs:02d}"

    @property
    def last_alert_ago(self) -> str:
        if not self.last_alert_info:
            return ""
        ago = int(time.time() - self.last_alert_info["time"])
        if ago < 60:
            return f"{ago}s ago"
        mins = ago // 60
        if mins < 60:
            return f"{mins}m ago"
        return f"{mins // 60}h ago"
