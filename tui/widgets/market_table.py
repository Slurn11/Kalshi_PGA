"""DataTable showing top opportunities sorted by edge."""

from textual.widgets import DataTable, Static
from rich.text import Text


class MarketTableEmpty(Static):
    """Placeholder when no opportunities exist."""

    def render(self) -> Text:
        t = Text()
        t.append("\n  📊 Top Opportunities\n", style="bold #00aa00")
        t.append("  No evaluated markets yet.\n", style="#555555")
        t.append("  Opportunities will appear here during live tournaments.\n", style="#444444")
        return t


class MarketTable(DataTable):
    """Top 10 current opportunities table."""

    def on_mount(self):
        self.add_columns("#", "Player", "Type", "Model %", "Ask", "Spread", "Edge", "Signal")
        self.cursor_type = "row"
        self.zebra_stripes = True
        self.show_header = True

    def update_markets(self, evaluations: list):
        """Refresh table with current cycle evaluations sorted by edge."""
        self.clear()
        if not evaluations:
            return
        sorted_evals = sorted(evaluations, key=lambda e: e.get("edge", 0), reverse=True)
        for i, ev in enumerate(sorted_evals[:10], 1):
            dg_pct = f"{ev['dg_prob'] * 100:.0f}%"
            ask = f"{ev['ask']:.0f}¢"
            spread = f"{ev['spread']:.0f}¢"
            edge = f"{ev['edge']:+.1f}%"
            decision = ev["decision"]
            valid = ev.get("validation", "")
            if decision == "BET":
                signal = "✅ BET"
            elif decision == "WATCH":
                signal = "⏸️ WATCH"
            else:
                signal = "· PASS"

            self.add_row(
                str(i),
                ev["player"],
                ev["type"].upper(),
                dg_pct,
                ask,
                spread,
                edge,
                signal,
            )
