"""Scrolling evaluation log in the main area."""

from datetime import datetime

from textual.widgets import RichLog
from rich.text import Text


class EvalLog(RichLog):
    """Scrolling log of cycle activity and evaluations."""

    def show_idle_message(self, countdown: int = 0):
        """Show a friendly idle/waiting message."""
        self.clear()
        t = Text()
        t.append("\n\n\n")
        t.append("                    ⏳  No tournament in progress\n\n", style="bold #888888")
        if countdown > 0:
            mins, secs = divmod(countdown, 60)
            if mins:
                t.append(f"                    Next scan in: {mins}m {secs}s\n", style="#555555")
            else:
                t.append(f"                    Next scan in: {secs}s\n", style="#555555")
        else:
            t.append("                    Scanning...\n", style="#555555")
        t.append("\n")
        t.append("                    When a tournament goes live, you'll see:\n", style="#444444")
        t.append("                      • Market scanning results\n", style="#006600")
        t.append("                      • Edge evaluations per player\n", style="#006600")
        t.append("                      • BET / WATCH / PASS decisions\n", style="#006600")
        t.append("                      • Alert notifications\n", style="#006600")
        self.write(t)

    def log_line(self, message: str, style: str = "#00cc00"):
        ts = datetime.now().strftime("%-I:%M:%S%p").lower()
        line = Text()
        line.append(f" {ts}  ", style="#006600")
        line.append(message, style=style)
        self.write(line)

    def log_cycle_start(self, snapshot):
        self.write(Text(""))  # blank line separator
        divider = Text()
        divider.append(" ─── Scan Cycle ", style="#00aa00")
        divider.append("─" * 44, style="#003300")
        self.write(divider)

        self.log_line("Fetching Data Golf probabilities...")

        if not snapshot.tournament_active:
            self.log_line("No live tournament data available", style="#888888")
            self.log_line(
                f"Will retry in ~{snapshot.positions_checked or 60} minutes",
                style="#555555",
            )
            return

        self.log_line(
            f"✓ {snapshot.players_loaded} players loaded",
            style="#00ff00",
        )
        self.log_line("Scanning Kalshi markets...")
        self.log_line(
            f"✓ Found {snapshot.markets_found} markets across 5 series",
            style="#00ff00",
        )
        if snapshot.round_num:
            self.log_line(
                f"Round {snapshot.round_num} of 4  •  Min edge = {snapshot.min_edge:.1f}%",
                style="#00aa00",
            )

        # Filter summary
        edge_skips = sum(1 for s in snapshot.skipped if s["reason"] == "edge_too_low")
        spread_skips = sum(1 for s in snapshot.skipped if s["reason"] == "spread_too_wide")
        other_skips = len(snapshot.skipped) - edge_skips - spread_skips
        n_eval = len(snapshot.evaluations)

        self.log_line("Applying filters...")
        if edge_skips:
            self.log_line(f"  ├ {edge_skips} skipped — edge too small", style="#555555")
        if spread_skips:
            self.log_line(f"  ├ {spread_skips} skipped — spread too wide", style="#555555")
        if other_skips:
            self.log_line(f"  ├ {other_skips} skipped — other", style="#555555")
        self.log_line(
            f"  └ {n_eval} passed filters → evaluating with Claude",
            style="#00aa00",
        )

    def log_evaluation(self, ev: dict):
        player = ev["player"]
        mtype = ev["type"].upper()
        dg = ev["dg_prob"] * 100
        ask = ev["ask"]
        bid = ev["bid"]
        edge = ev["edge"]
        decision = ev["decision"]

        decision_config = {
            "BET": ("✅", "bold #00ff00"),
            "WATCH": ("⏸️", "#ffff00"),
            "PASS": ("·", "#555555"),
        }
        icon, style = decision_config.get(decision, ("·", "#555555"))

        line = Text()
        ts = datetime.now().strftime("%-I:%M:%S%p").lower()
        line.append(f" {ts}  ", style="#006600")
        line.append(f"{icon} ", style=style)
        line.append(f"{decision:<5}", style=style)
        line.append(f" {player} ", style="#00cc00" if decision == "BET" else "#008800")
        line.append(f"{mtype:<6}", style="#007700")
        line.append(f" {edge:+.1f}% edge", style="#00aa00" if edge > 10 else "#007700")
        line.append(f"  DG={dg:.0f}%", style="#006600")
        line.append(f"  ask={ask:.0f}¢", style="#006600")
        self.write(line)

        # Show reasoning snippet for BET decisions
        if decision == "BET" and ev.get("reasoning"):
            reason = ev["reasoning"][:80]
            self.log_line(f"       └ {reason}", style="#005500")

    def log_cycle_end(self, snapshot):
        alerts = snapshot.alerts_sent
        pos = snapshot.positions_checked
        parts = []
        if alerts:
            parts.append(f"📬 {alerts} alert(s) sent")
        if pos:
            parts.append(f"checked {pos} open positions")
        msg = "Scan complete"
        if parts:
            msg += " — " + ", ".join(parts)
        self.log_line(msg, style="#00aa00")

    def log_error(self, error_msg: str):
        self.log_line(f"⚠️  {error_msg}", style="#ff5555")
