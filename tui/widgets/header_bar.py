"""Top header bar showing tournament, status, connections, and clock."""

from datetime import datetime

from textual.reactive import reactive
from textual.widgets import Static
from rich.text import Text


PHASE_BADGES = {
    "PRE_TOURNAMENT": (" PRE-TOURNAMENT ", "bold #ffffff on #0055aa"),
    "LIVE_ROUND": (" LIVE R{round} ", "bold #000000 on #00ff00"),
    "BETWEEN_ROUNDS": (" BETWEEN ROUNDS ", "bold #000000 on #ffff00"),
    "FINISHED": (" FINISHED ", "#888888 on #333333"),
    "IDLE": (" IDLE ", "#555555 on #111111"),
}


class HeaderBar(Static):
    """Single-line header with tournament info, status, connections, clock."""

    status = reactive("STARTING")
    tournament_name = reactive("")
    round_indicator = reactive("")
    dg_ok = reactive(False)
    kalshi_ok = reactive(False)
    claude_ok = reactive(True)
    countdown = reactive(0)
    phase = reactive("IDLE")
    round_num = reactive(0)

    def render(self) -> Text:
        t = Text()
        t.append(" ⛳ PGA GOLF AGENT", style="bold #00ff00")

        # Phase badge
        badge_template, badge_style = PHASE_BADGES.get(
            self.phase, (" IDLE ", "#555555 on #111111")
        )
        badge_label = badge_template.format(round=self.round_num or "?")
        t.append(f"  {badge_label}", style=badge_style)

        # Tournament name
        if self.tournament_name:
            t.append(f"  {self.tournament_name}", style="bold #00cc00")
        elif self.phase not in ("IDLE", "FINISHED"):
            t.append("  PGA Tournament", style="#00cc00")

        t.append("  ", style="")

        # Status badge
        badges = {
            "SCANNING": (" SCANNING ", "bold #000000 on #ffff00"),
            "IDLE": (" LIVE ", "bold #000000 on #00ff00"),
            "WAITING": (" WAITING ", "#888888 on #222222"),
            "STARTING": (" STARTING ", "#000000 on #555555"),
            "ERROR": (" ERROR ", "bold #ffffff on #aa0000"),
        }
        label, style = badges.get(self.status, (" IDLE ", "#555555 on #111111"))
        t.append(label, style=style)

        t.append("  ", style="")

        # Connection dots
        def dot(ok, label):
            t.append("●", style="#00ff00" if ok else "#444444")
            t.append(f"{label} ", style="#006600" if ok else "#333333")

        dot(self.dg_ok, "DG")
        dot(self.kalshi_ok, "Kalshi")
        dot(self.claude_ok, "Claude")

        # Countdown + clock
        now = datetime.now().strftime("%H:%M:%S")
        if self.countdown > 0:
            mins, secs = divmod(self.countdown, 60)
            if mins:
                t.append(f"  next scan {mins}m{secs:02d}s", style="#555555")
            else:
                t.append(f"  next scan {secs}s", style="#555555")
        t.append(f"  {now}", style="#00aa00")

        return t
