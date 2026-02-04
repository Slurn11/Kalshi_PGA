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
        interval_min = dm.poll_interval // 60
        if interval_min >= 1:
            _row(t, "Poll Interval", f"{interval_min}m")
        else:
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

        # RECOMMENDATIONS (agent BET decisions)
        _heading(t, "RECOMMENDATIONS")
        rec_stats = dm.recommendation_stats
        if rec_stats and rec_stats.get("total_recommendations", 0) > 0:
            total = rec_stats["total_recommendations"]
            settled = rec_stats.get("settled", 0)
            if settled > 0:
                wr = rec_stats.get("win_rate", 0) * 100
                wr_style = "#00ff00" if wr >= 50 else "#ff5555"
                _row(t, "Win Rate", f"{wr:.0f}%", wr_style)
                _row(t, "Record", f"{rec_stats['wins']}W-{rec_stats['losses']}L")
            _row(t, "Total Recs", str(total), "#888888")
        else:
            t.append(" No recommendations yet\n", style="#555555")

        # MY BETS (manual positions)
        _heading(t, "MY BETS")
        manual = dm.manual_stats
        if manual and (manual.get("open_count", 0) + manual.get("closed_count", 0)) > 0:
            if manual.get("closed_count", 0) > 0:
                wr = manual.get("win_rate", 0) * 100
                wr_style = "#00ff00" if wr >= 50 else "#ff5555"
                _row(t, "Win Rate", f"{wr:.0f}%", wr_style)
                pnl = manual.get("total_realized_pnl", 0)
                _row(t, "Profit", f"{pnl:+.0f}¢", "#00ff00" if pnl >= 0 else "#ff5555")
                _row(t, "Record", f"{manual['wins']}W-{manual['losses']}L")
            _row(t, "Open Bets", str(manual.get("open_count", 0)))
        else:
            t.append(" Press B to add bet\n", style="#555555")

        # CLV STATS (for recommendations)
        _heading(t, "CLV TRACKING")
        clv = dm.clv_stats
        if clv and clv.get("total_bets", 0) > 0:
            avg_clv = clv.get("avg_clv_cents", 0)
            _row(t, "Avg CLV", f"{avg_clv:+.1f}¢", "#00ff00" if avg_clv >= 0 else "#ff5555")
            _row(t, "Positive CLV", f"{clv.get('positive_clv_pct', 0):.0f}%")
        else:
            t.append(" No CLV data yet\n", style="#555555")

        # PHASE PERFORMANCE
        phase_stats = dm.phase_stats
        if phase_stats:
            _heading(t, "BY PHASE")
            phase_labels = {
                "PRE_TOURNAMENT": "Pre-Tourney",
                "LIVE_ROUND": "Live Rounds",
                "BETWEEN_ROUNDS": "Between Rds",
            }
            for phase_key, label in phase_labels.items():
                ps_phase = phase_stats.get(phase_key)
                if ps_phase and ps_phase.get("total", 0) > 0:
                    w = ps_phase["wins"]
                    l = ps_phase["losses"]
                    pnl = ps_phase.get("pnl", 0)
                    pnl_style = "#00ff00" if pnl >= 0 else "#ff5555"
                    _row(t, label, f"{w}W-{l}L | {pnl:+.0f}¢", pnl_style)

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
