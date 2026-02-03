"""Left sidebar with stats panels."""

import time

from textual.widgets import Static
from rich.text import Text


def _row(t: Text, label: str, value: str, val_style: str = "#00ff00"):
    """Append a label: value row."""
    t.append(f" {label:<15}", style="#007700")
    t.append(f"{value}\n", style=val_style)


def _heading(t: Text, title: str):
    t.append(f"── {title} ", style="bold #00aa00")
    t.append("─" * max(0, 18 - len(title)) + "\n", style="#003300")


class Sidebar(Static):
    """Left sidebar showing system status, config, scan results, performance, leaderboard."""

    def __init__(self, data_manager, **kwargs):
        super().__init__(**kwargs)
        self.dm = data_manager

    def render(self) -> Text:
        dm = self.dm
        t = Text()

        # STATUS
        _heading(t, "STATUS")
        status_styles = {
            "SCANNING": "bold #ffff00",
            "IDLE": "bold #00ff00",
            "WAITING": "#888888",
            "STARTING": "#555555",
            "ERROR": "bold #ff0000",
        }
        status_icons = {
            "SCANNING": "🔍",
            "IDLE": "🟢",
            "WAITING": "⏳",
            "STARTING": "⏳",
            "ERROR": "🔴",
        }
        icon = status_icons.get(dm.status, "")
        _row(t, "Engine", f"{icon} {dm.status}", status_styles.get(dm.status, "#555555"))
        _row(t, "Uptime", dm.uptime_str)
        _row(t, "Cycles", str(dm.cycle_count))
        _row(t, "Poll Interval", f"{dm.poll_interval}s")

        # SETTINGS
        _heading(t, "SETTINGS")
        cycle = dm.current_cycle
        min_edge = cycle.min_edge if cycle and cycle.min_edge > 0 else dm.base_min_edge
        _row(t, "Min Edge", f"{min_edge:.1f}%")
        _row(t, "Max Spread", f"{dm.max_spread}¢")
        _row(t, "Alert Cooldown", f"{dm.alert_cooldown}m")

        # CURRENT SCAN
        _heading(t, "LAST SCAN")
        if cycle and cycle.tournament_active:
            _row(t, "Markets", str(cycle.markets_found))
            _row(t, "Evaluated", str(len(cycle.evaluations)))
            n_skip = len(cycle.skipped)
            _row(t, "Filtered Out", str(n_skip), "#555555")
            alert_style = "bold #00ff00" if cycle.alerts_sent else "#555555"
            _row(t, "Alerts Sent", str(cycle.alerts_sent), alert_style)
        elif cycle and not cycle.tournament_active:
            t.append(" No live data\n", style="#555555")
        else:
            t.append(" Waiting...\n", style="#555555")

        # PERFORMANCE
        _heading(t, "PERFORMANCE")
        ps = dm.position_stats
        acc = dm.accuracy_stats
        clv = dm.clv_stats
        if ps and (ps.get("open_count", 0) + ps.get("closed_count", 0)) > 0:
            wr = acc.get("accuracy", 0) * 100 if acc else 0
            wr_style = "#00ff00" if wr >= 50 else "#ff5555"
            _row(t, "Win Rate", f"{wr:.0f}%", wr_style)
            pnl = ps.get("total_realized_pnl", 0)
            _row(t, "Profit", f"{pnl:+.0f}¢", "#00ff00" if pnl >= 0 else "#ff5555")
            avg_clv = clv.get("avg_clv_cents", 0) if clv else 0
            _row(t, "Avg CLV", f"{avg_clv:+.1f}¢", "#00ff00" if avg_clv >= 0 else "#ff5555")
            _row(t, "Open Bets", str(ps.get("open_count", 0)))
            _row(t, "Closed Bets", str(ps.get("closed_count", 0)), "#888888")
        else:
            t.append(" No bets yet\n", style="#555555")

        # LAST ALERT
        if dm.last_alert_info:
            _heading(t, "LAST ALERT")
            info = dm.last_alert_info
            _row(t, "Player", info["player"], "bold #00ff00")
            _row(t, "Type", info["type"].upper(), "#00cc00")
            _row(t, "When", dm.last_alert_ago, "#00aa00")

        # LEADERBOARD
        _heading(t, "LEADERBOARD")
        if cycle and cycle.leaderboard:
            lb_items = sorted(
                cycle.leaderboard.items(),
                key=lambda x: x[1].get("position", 999),
            )[:5]
            for name, info in lb_items:
                pos = info.get("position", "?")
                score = info.get("score_to_par", 0)
                score_str = f"{score:+d}" if isinstance(score, (int, float)) else str(score)
                short = name[:11].ljust(11)
                t.append(f" {str(pos):<3}", style="#00aa00")
                t.append(f"{short} ", style="#00cc00")
                t.append(f"{score_str}\n", style="#00ff00")
            rnd = cycle.round_num
            if rnd:
                t.append(f" Round {rnd} of 4", style="bold #00aa00")
                first = lb_items[0][1] if lb_items else {}
                thru = first.get("thru", "")
                if thru:
                    t.append(f"  thru {thru}", style="#006600")
                t.append("\n", style="")
        else:
            t.append(" No tournament active\n", style="#555555")

        return t
