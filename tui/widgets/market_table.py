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
    """Top 15 current opportunities table showing all verified positive edges."""

    def on_mount(self):
        self.add_columns("#", "Player", "Type", "Model %", "Ask", "Spread", "Edge", "Status")
        self.cursor_type = "row"
        self.zebra_stripes = True
        self.show_header = True

    def update_markets(self, top_edges: list, min_edge: float = 7.0):
        """Refresh table with all verified positive edges sorted by edge."""
        self.clear()
        if not top_edges:
            return

        for i, te in enumerate(top_edges[:15], 1):
            dg_pct = f"{te['dg_prob'] * 100:.0f}%"
            ask = f"{te['ask']:.0f}¢✓"  # All edges are verified now
            bid = te.get('bid', 0)
            spread = te['ask'] - bid if bid else 0
            spread_str = f"{spread:.0f}¢"
            edge = te['edge']
            edge_str = f"{edge:+.1f}%"
            bettable = te.get('bettable', edge >= min_edge)

            # Status indicator based on edge size
            if bettable:
                status = "🟢 BETTABLE"
            elif edge >= 5:
                status = "🟡 CLOSE"
            elif edge >= 3:
                status = "🟡 watching"
            else:
                status = "⚪ small"

            self.add_row(
                str(i),
                te["player"],
                te["type"].upper(),
                dg_pct,
                ask,
                spread_str,
                edge_str,
                status,
            )
