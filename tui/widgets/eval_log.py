"""Scrolling evaluation log in the main area."""

from datetime import datetime

from textual.widgets import RichLog
from rich.text import Text

from models import ScanStage


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

    def log_stage(self, stage: ScanStage):
        """Render a pipeline stage as a real-time log entry."""
        name = stage.name
        d = stage.data

        if name == "fetch_data":
            status = d.get("status", "")
            if status == "fetching":
                self.write(Text(""))
                divider = Text()
                divider.append(" ─── Scan Cycle ", style="#00aa00")
                divider.append("─" * 44, style="#003300")
                self.write(divider)
                self.log_line("Fetching Data Golf probabilities...", style="#007700")
            elif status == "ok":
                self.log_line(
                    f"  ├── ✓ {d.get('players', 0)} players loaded",
                    style="#00ff00",
                )
            elif status == "empty":
                self.log_line("  └── No live data available", style="#888888")

        elif name == "discover_markets":
            status = d.get("status", "")
            if status == "fetching":
                self.log_line("Discovering Kalshi golf markets...", style="#007700")
            elif status == "ok":
                self.log_line(
                    f"  ├── ✓ {d.get('count', 0)} markets found across 6 series",
                    style="#00ff00",
                )
            elif status == "empty":
                self.log_line("  └── No markets found", style="#888888")

        elif name == "match_players":
            matched = d.get("matched", 0)
            unmatched = d.get("unmatched", 0)
            self.log_line(
                f"  ├── Matched {matched} markets, {unmatched} unmatched",
                style="#00aa00",
            )
            unmatched_names = d.get("unmatched_names", [])
            if unmatched_names:
                names_str = ", ".join(unmatched_names[:5])
                if unmatched > 5:
                    names_str += f" (+{unmatched - 5} more)"
                self.log_line(f"  │   Unmatched: {names_str}", style="#555555")

        elif name == "evaluating":
            player = d.get("player", "?")
            mtype = d.get("type", "?").upper()
            dg = d.get("dg_prob", 0) * 100
            ask = d.get("ask", 0)
            bid = d.get("bid", 0)
            spread = d.get("spread", 0)
            edge = d.get("edge", 0)
            kelly = d.get("kelly", {})
            kelly_str = ""
            if isinstance(kelly, dict) and kelly.get("stake_dollars"):
                kelly_str = f"  kelly=${kelly['stake_dollars']:.0f}"

            line = Text()
            ts = datetime.now().strftime("%-I:%M:%S%p").lower()
            line.append(f" {ts}  ", style="#006600")
            line.append("  ├── ", style="#003300")
            line.append("⏳ ", style="#ffff00")
            line.append(f"{player} ", style="#00cc00")
            line.append(f"{mtype:<6}", style="#007700")
            line.append(f" DG={dg:.0f}%", style="#006600")
            line.append(f"  ask={ask:.0f}¢ bid={bid:.0f}¢", style="#006600")
            line.append(f"  spread={spread:.0f}¢", style="#006600")
            line.append(f"  edge={edge:+.1f}%", style="#00aa00" if edge > 10 else "#007700")
            if kelly_str:
                line.append(kelly_str, style="#006600")
            self.write(line)

        elif name == "claude_decision":
            decision = d.get("decision", "?")
            confidence = d.get("confidence", 0)
            reasoning = d.get("reasoning", "")[:80]
            player = d.get("player", "?")
            mtype = d.get("type", "?").upper()

            decision_config = {
                "BET": ("✅", "bold #00ff00"),
                "WATCH": ("⏸️", "#ffff00"),
                "PASS": ("·", "#555555"),
            }
            icon, style = decision_config.get(decision, ("·", "#555555"))

            line = Text()
            ts = datetime.now().strftime("%-I:%M:%S%p").lower()
            line.append(f" {ts}  ", style="#006600")
            line.append("  │   ", style="#003300")
            line.append(f"{icon} ", style=style)
            line.append(f"{decision:<5}", style=style)
            if confidence:
                line.append(f" ({confidence:.0f}%)", style="#006600")
            line.append(f"  {reasoning}", style="#005500")
            self.write(line)

        elif name == "scan_complete":
            evaluated = d.get("evaluated", 0)
            bets = d.get("bets", 0)
            watches = d.get("watches", 0)
            passes = d.get("passes", 0)
            alerts = d.get("alerts", 0)
            duration = d.get("duration", 0)
            edge_f = d.get("edge_filtered", 0)
            spread_f = d.get("spread_filtered", 0)
            top_edges = d.get("top_edges", [])

            self.log_line(
                f"  └── Scan complete in {duration:.1f}s",
                style="#00aa00",
            )
            parts = []
            if evaluated:
                parts.append(f"{evaluated} evaluated")
            if bets:
                parts.append(f"{bets} BET")
            if watches:
                parts.append(f"{watches} WATCH")
            if passes:
                parts.append(f"{passes} PASS")
            if edge_f:
                parts.append(f"{edge_f} edge-filtered")
            if spread_f:
                parts.append(f"{spread_f} spread-filtered")
            if parts:
                self.log_line(f"       {' | '.join(parts)}", style="#006600")
            if alerts:
                self.log_line(f"       📬 {alerts} alert(s) sent", style="bold #00ff00")

            # Show top edges for visibility
            positive_edges = d.get("positive_edges", 0)
            bettable_edges = d.get("bettable_edges", 0)
            min_edge_threshold = d.get("min_edge", 7.0)

            if top_edges or positive_edges > 0:
                self.write(Text(""))
                header = Text()
                header.append("  ─── Top Edges (verified) ", style="#00aa00")
                header.append("─" * 33, style="#003300")
                self.write(header)

                # Summary line
                summary = Text()
                summary.append("  ", style="")
                summary.append(f"Positive: {positive_edges}", style="#00aa00")
                summary.append("  │  ", style="#333333")
                if bettable_edges > 0:
                    summary.append(f"Bettable (≥{min_edge_threshold:.0f}%): {bettable_edges}", style="bold #00ff00")
                else:
                    summary.append(f"Bettable (≥{min_edge_threshold:.0f}%): 0", style="#555555")
                self.write(summary)
                self.write(Text(""))

                for i, te in enumerate(top_edges[:20]):
                    player = te.get("player", "?")
                    mtype = te.get("type", "?").upper()
                    dg = te.get("dg_prob", 0) * 100
                    ask = te.get("ask", 0)
                    edge = te.get("edge", 0)
                    bettable = te.get("bettable", False)

                    line = Text()
                    line.append(f"  {i+1:>2}. ", style="#006600")

                    # Color code player name by edge
                    if edge >= min_edge_threshold:
                        line.append(f"{player:<20}", style="bold #00ff00")
                    elif edge >= 5:
                        line.append(f"{player:<20}", style="#00cc00")
                    elif edge >= 3:
                        line.append(f"{player:<20}", style="#ffff00")
                    else:
                        line.append(f"{player:<20}", style="#888888")

                    line.append(f"{mtype:<7}", style="#007700")
                    line.append(f"DG {dg:4.1f}%", style="#006600")
                    line.append(f" vs ", style="#444444")
                    line.append(f"{ask:>2}¢", style="#006600")
                    line.append(f" = ", style="#444444")

                    # Edge value with status indicator
                    if edge >= min_edge_threshold:
                        line.append(f"{edge:+5.1f}%", style="bold #00ff00")
                        line.append(" 🟢 BET", style="#00ff00")
                    elif edge >= 5:
                        line.append(f"{edge:+5.1f}%", style="#00cc00")
                        line.append(" 🟡 CLOSE", style="#888888")
                    elif edge >= 3:
                        line.append(f"{edge:+5.1f}%", style="#ffff00")
                        line.append(" 🟡 watch", style="#555555")
                    elif edge > 0:
                        line.append(f"{edge:+5.1f}%", style="#888888")
                        line.append(" ⚪", style="#444444")
                    else:
                        line.append(f"{edge:+5.1f}%", style="#555555")
                        line.append(" ✗", style="#444444")
                    self.write(line)
            else:
                # No positive edges at all
                self.write(Text(""))
                self.write(Text("  No positive edges found this scan", style="#555555"))

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
            f"✓ Found {snapshot.markets_found} markets across 6 series",
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
