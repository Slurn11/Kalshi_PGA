"""Main Textual application for the PGA Golf Betting Dashboard."""

import asyncio
import logging
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, Center
from textual.message import Message
from textual.widgets import Footer, Static, Input, Button, Label, Select
from textual.screen import ModalScreen

from tui.data_manager import DataManager
from tui.widgets.header_bar import HeaderBar
from tui.widgets.sidebar import Sidebar
from tui.widgets.eval_log import EvalLog
from tui.widgets.market_table import MarketTable
from tui.scheduler import run_polling_loop
from database import add_manual_position


HELP_TEXT = """
[bold #00ff00]⛳ PGA Golf Agent — Help[/]

[bold #00aa00]What This Does[/]
Monitors Kalshi PGA golf prediction markets and
compares prices against Data Golf's statistical model.
When the model sees an edge, Claude AI evaluates
whether the opportunity is worth betting on.

[bold #00aa00]Key Terms[/]
[#00cc00]Edge[/]      How much better our model's price is vs
         the market. Higher = better opportunity.
[#00cc00]DG%[/]       Data Golf's estimated probability.
[#00cc00]Ask[/]       The price to buy YES on Kalshi (in cents).
[#00cc00]Spread[/]    Gap between buy/sell price. Wider = less
         liquid, harder to trade.
[#00cc00]CLV[/]       Closing Line Value. If the line moves our
         way after we bet, that's +CLV (good sign).

[bold #00aa00]Decisions[/]
[bold #00ff00]✅ BET[/]    Strong opportunity — alert sent
[#ffff00]⏸️ WATCH[/]  Interesting but not strong enough
[#555555]· PASS[/]    Not worth pursuing

[bold #00aa00]Keys[/]
[#00cc00]Q[/]  Quit    [#00cc00]R[/]  Force refresh
[#00cc00]F[/]  Scan Now   [#00cc00]P[/]  Show positions
[#00cc00]H[/]  Toggle help
[#00cc00]B[/]  Add manual bet (auto-settles via Kalshi API)
"""


class HelpPanel(Static):
    """Overlay help panel."""

    def render(self):
        return HELP_TEXT


class AddBetScreen(ModalScreen):
    """Modal screen for adding a manual bet."""

    BINDINGS = [("escape", "dismiss", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="add-bet-dialog"):
            yield Label("[bold #00ff00]Add Manual Bet[/]", id="add-bet-title")
            yield Label("Ticker (required for auto-settle):")
            yield Input(placeholder="e.g., KXPGATOP5-25JAN30-MCILROY", id="ticker-input")
            yield Label("Player Name:")
            yield Input(placeholder="e.g., Scottie Scheffler", id="player-input")
            yield Label("Market Type:")
            yield Select(
                [(t, t) for t in ["winner", "top5", "top10", "top20", "make_cut"]],
                id="type-select",
                value="winner",
            )
            yield Label("Entry Price (cents):")
            yield Input(placeholder="e.g., 45", id="price-input")
            with Horizontal(id="add-bet-buttons"):
                yield Button("Add Bet", variant="success", id="add-btn")
                yield Button("Cancel", variant="error", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "add-btn":
            ticker = self.query_one("#ticker-input", Input).value.strip()
            player = self.query_one("#player-input", Input).value.strip()
            market_type = self.query_one("#type-select", Select).value
            price_str = self.query_one("#price-input", Input).value.strip()
            if ticker and player and price_str:
                try:
                    price = float(price_str)
                    self.dismiss({"ticker": ticker, "player": player, "type": market_type, "price": price})
                except ValueError:
                    pass
            else:
                self.dismiss(None)


class StageUpdated(Message):
    """Posted when a new pipeline stage arrives."""

    def __init__(self, stage):
        super().__init__()
        self.stage = stage


class GolfDashboard(App):
    """PGA Golf Agent Terminal Dashboard."""

    class DataUpdated(Message):
        """Posted when the DataManager has new data."""

    CSS_PATH = str(Path(__file__).parent / "styles.tcss")
    TITLE = "PGA Golf Agent"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "force_refresh", "Refresh"),
        ("f", "force_scan", "Scan Now"),
        ("p", "toggle_positions", "Positions"),
        ("h", "toggle_help", "Help"),
        ("b", "add_bet", "Add Bet"),
    ]

    def __init__(self):
        super().__init__()
        # Remove console handlers to prevent log output from corrupting TUI display
        for handler in logging.root.handlers[:]:
            if isinstance(handler, logging.StreamHandler) and handler.stream in (sys.stdout, sys.stderr):
                logging.root.removeHandler(handler)
        self.dm = DataManager()
        self.dm.set_update_callback(self._on_data_update)
        self.dm.set_stage_callback(self._on_stage_update)
        self._poll_task = None
        self._help_visible = False
        self._showed_idle = False
        self._idle_shown_with_countdown = False

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="header")
        with Horizontal(id="main-container"):
            yield Sidebar(self.dm, id="sidebar")
            with Vertical(id="main-area"):
                yield EvalLog(
                    id="eval-log", highlight=True, markup=False, auto_scroll=True
                )
                yield MarketTable(id="market-table-container")
                yield HelpPanel(id="help-panel")
        yield Footer()

    def on_mount(self):
        # Hide help panel initially
        self.query_one("#help-panel").display = False
        # Show welcome message
        eval_log: EvalLog = self.query_one("#eval-log", EvalLog)
        eval_log.log_line("PGA Golf Agent starting up...", style="bold #00ff00")
        eval_log.log_line("Press H for help  •  F for scan now  •  Q to quit", style="#555555")
        # Start poller and UI tick
        self._poll_task = asyncio.create_task(run_polling_loop(self.dm))
        self.set_interval(1.0, self._tick)

    def _on_data_update(self):
        """Called from DataManager when data changes. Post message to UI."""
        self.post_message(self.DataUpdated())

    def _on_stage_update(self, stage):
        """Called from DataManager when a new stage arrives."""
        self.post_message(StageUpdated(stage))

    def on_stage_updated(self, message: StageUpdated):
        """Handle real-time stage updates."""
        eval_log: EvalLog = self.query_one("#eval-log", EvalLog)
        eval_log.log_stage(message.stage)

    def on_golf_dashboard_data_updated(self, message: DataUpdated):
        """Handle data update message."""
        self._refresh_ui()

    def _refresh_ui(self):
        """Refresh all widgets with latest data."""
        header: HeaderBar = self.query_one("#header", HeaderBar)
        sidebar: Sidebar = self.query_one("#sidebar", Sidebar)
        eval_log: EvalLog = self.query_one("#eval-log", EvalLog)
        market_table: MarketTable = self.query_one(
            "#market-table-container", MarketTable
        )

        # Update header
        header.status = self.dm.status
        header.dg_ok = self.dm.dg_connected
        header.kalshi_ok = self.dm.kalshi_connected
        header.claude_ok = self.dm.claude_connected
        header.phase = self.dm.phase
        header.tournament_name = self.dm.tournament_name

        cycle = self.dm.current_cycle
        if cycle and cycle.tournament_active:
            self._showed_idle = False
            header.round_num = cycle.round_num or 0
            if cycle.round_num:
                header.round_indicator = f"Round {cycle.round_num} of 4"
            # Log cycle (only if stages aren't already doing real-time logging)
            if not self.dm.stage_log:
                eval_log.log_cycle_start(cycle)
                for ev in cycle.evaluations:
                    eval_log.log_evaluation(ev)
                eval_log.log_cycle_end(cycle)
            # Update market table with all verified positive edges
            market_table.update_markets(cycle.top_edges, cycle.min_edge)
            market_table.display = True
        elif cycle and cycle.error:
            eval_log.log_error(cycle.error)
            header.tournament_name = ""
            header.round_indicator = ""
        elif cycle:
            # No tournament
            header.round_indicator = ""
            countdown = self.dm.next_cycle_countdown
            eval_log.show_idle_message(countdown)
            self._showed_idle = True
            market_table.display = False

        # Refresh sidebar
        sidebar.refresh()

    def _tick(self):
        """Called every second for clock, countdown, and uptime updates."""
        header: HeaderBar = self.query_one("#header", HeaderBar)
        header.countdown = self.dm.next_cycle_countdown
        header.phase = self.dm.phase
        if self.dm.tournament_name:
            header.tournament_name = self.dm.tournament_name
        header.refresh()
        # Refresh sidebar every second for uptime
        sidebar: Sidebar = self.query_one("#sidebar", Sidebar)
        sidebar.refresh()
        # Update idle countdown if showing idle screen
        if self._showed_idle and self.dm.next_cycle_countdown > 0:
            eval_log: EvalLog = self.query_one("#eval-log", EvalLog)
            eval_log.show_idle_message(self.dm.next_cycle_countdown)

    def action_force_refresh(self):
        self._refresh_ui()

    def action_force_scan(self):
        """Trigger an immediate scan cycle."""
        self.dm.force_scan.set()
        eval_log: EvalLog = self.query_one("#eval-log", EvalLog)
        eval_log.log_line("Manual scan triggered...", style="bold #ffff00")

    def action_toggle_positions(self):
        """Show open positions in the eval log."""
        eval_log: EvalLog = self.query_one("#eval-log", EvalLog)
        positions = self.dm.open_positions
        if positions:
            eval_log.log_line("── Open Positions ──", style="bold #00aa00")
            for p in positions:
                eval_log.log_line(
                    f"  {p['player_name']} {p['market_type'].upper()} "
                    f"@ {p['entry_price']}¢  edge={p['entry_edge']:+.1f}%",
                    style="#00cc00",
                )
        else:
            eval_log.log_line("No open positions", style="#555555")

    def action_toggle_help(self):
        """Toggle the help panel."""
        help_panel = self.query_one("#help-panel")
        self._help_visible = not self._help_visible
        help_panel.display = self._help_visible
        if self._help_visible:
            # Hide market table when help is shown
            self.query_one("#market-table-container").display = False
        else:
            # Restore market table if there are evaluations
            cycle = self.dm.current_cycle
            if cycle and cycle.tournament_active and cycle.evaluations:
                self.query_one("#market-table-container").display = True

    def action_add_bet(self):
        """Open dialog to add a manual bet."""
        def handle_result(result):
            if result:
                pos_id = add_manual_position(
                    player_name=result["player"],
                    market_type=result["type"],
                    entry_price=result["price"],
                    tournament_name=self.dm.tournament_name or None,
                    ticker=result["ticker"],
                )
                eval_log: EvalLog = self.query_one("#eval-log", EvalLog)
                eval_log.log_line(
                    f"Added manual bet: {result['player']} {result['type']} @ {result['price']}¢ ({result['ticker']})",
                    style="bold #00ff00",
                )
        self.push_screen(AddBetScreen(), handle_result)
