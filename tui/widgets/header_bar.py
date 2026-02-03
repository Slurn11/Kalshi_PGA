"""Top header bar showing tournament, status, connections, and clock."""

from datetime import datetime

from textual.reactive import reactive
from textual.widgets import Static
from rich.text import Text


class HeaderBar(Static):
    """Single-line header with tournament info, status, connections, clock."""

    status = reactive("STARTING")
    tournament_name = reactive("")
    round_indicator = reactive("")
    dg_ok = reactive(False)
    kalshi_ok = reactive(False)
    claude_ok = reactive(True)
    countdown = reactive(0)

    def render(self) -> Text:
        t = Text()
        t.append(" ⛳ PGA GOLF AGENT", style="bold #00ff00")

        # Tournament name or idle message
        if self.tournament_name:
            t.append(f"  {self.tournament_name}", style="bold #00cc00")
            if self.round_indicator:
                t.append(f"  {self.round_indicator}", style="bold #00ff00")
        else:
            t.append("  No Live Tournament", style="#555555")

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
            t.append(f"  next scan {self.countdown}s", style="#555555")
        t.append(f"  {now}", style="#00aa00")

        return t
