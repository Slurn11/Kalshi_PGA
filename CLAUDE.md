# Kalshi PGA Golf Agent Betting System

## What This Is
An AI agent-based system that monitors Kalshi PGA golf prediction markets, compares prices against Data Golf's live model, uses Claude to reason about whether opportunities are worth betting, logs all decisions to SQLite and Excel, and sends Telegram recommendations. The system includes position tracking with market-type-aware exit logic: outright winner bets have active exit management, while all other bet types (top5/10/20, make_cut) are held to settlement.

## Project Structure
```
Kalshi_System/
├── .env                   # API keys, Telegram creds, thresholds
├── .gitignore             # Excludes .env, *.pem, __pycache__
├── requirements.txt       # requests, python-dotenv, cryptography, openpyxl
├── config.py              # Loads env vars, exports constants
├── models.py              # KalshiMarket dataclass (ticker, prices, implied prob)
├── kalshi_client.py       # Kalshi REST API client (RSA-PSS auth, market discovery)
├── kalshi_private_key.pem # RSA private key for Kalshi auth
├── datagolf_client.py     # Data Golf live in-play predictions + leaderboard
├── leaderboard.py         # ESPN PGA leaderboard fetcher (context for agent)
├── database.py            # SQLite schema + logging (opportunities/decisions/outcomes/positions)
├── agent.py               # Claude-powered betting evaluator (BET/PASS/WATCH)
├── positions.py           # Position management (open/close/exit conditions/stats)
├── alerts.py              # Telegram recommendations with cooldown + bid/ask/spread display
├── bet_logger.py          # Excel logging to bet_log.xlsx + historical stats
├── telegram_commands.py   # Telegram bot commands (/positions, /stats)
├── main.py                # Polling orchestrator loop
├── decisions.db           # SQLite database (created at runtime)
└── bet_log.xlsx           # Excel decision log (created at runtime)
```

## How It Works
1. **Data Golf** (`datagolf_client.py`) fetches live probabilities (win, top_5, top_10, top_20, make_cut) from `feeds.datagolf.com/preds/in-play`. Also builds leaderboard data from the same fetch. Names normalized from "Last, First" to "First Last".
2. **Kalshi** (`kalshi_client.py`) discovers open golf markets across 5 series (KXPGATOUR, KXPGA, KXPGATOP5, KXPGATOP10, KXPGATOP20). Parses golfer name and market type from title/subtitle. Uses RSA-PSS signing. 200ms delay between series to avoid rate limiting. Excludes markets with `yes_bid = 0` (no liquidity).
3. **Main loop** (`main.py`) fuzzy-matches player names between Data Golf and Kalshi (0.6 cutoff), calculates edge, applies filters:
   - Edge < 8% → skip (save API calls)
   - Spread > 15¢ → skip (market too illiquid)
4. **Agent** (`agent.py`) calls Claude (Sonnet) via Anthropic API with opportunity data + leaderboard context + historical accuracy stats + recent BET decisions. Returns structured JSON: `{decision, confidence, suggested_stake_pct, reasoning}`. Falls back to threshold logic if API fails.
5. **Database** (`database.py`) logs every opportunity, decision (with reasoning), and outcome. Agent queries its own history to inform future decisions.
6. **Excel** (`bet_logger.py`) logs all decisions (BET/PASS/WATCH) with full context. Provides historical win rate stats for Telegram alerts.
7. **Alerts** (`alerts.py`) sends Telegram recommendations for BET decisions. Shows bid/ask/spread, edge, confidence, stake suggestion, leaderboard context, historical stats, and reasoning. 30-min cooldown per ticker.
8. **Positions** (`positions.py`) tracks open/closed positions with entry/exit prices and P&L. Exit logic is market-type-aware:
   - **Winner markets:** Active exit management (profit target +15¢, edge flip to -8%)
   - **All other markets:** Hold to settlement (no early exit)
9. **Telegram Commands** (`telegram_commands.py`) responds to `/positions` and `/stats` commands.

## Agent Decision Flow
```
Every 60 seconds:
  1. Fetch Data Golf live probabilities (147 players)
  2. Discover Kalshi golf markets across 5 series (~60-110 liquid markets)
  3. Build leaderboard from Data Golf data
  4. For each market:
     a. Fuzzy-match golfer name to Data Golf
     b. Calculate edge = (DG prob - Kalshi implied) * 100
     c. If edge < 8% → skip
     d. If spread > 15¢ → skip (logged as "Spread too wide")
     e. Log opportunity to SQLite
     f. Send to Claude agent with full context
     g. Claude returns BET / PASS / WATCH + reasoning
     h. Log decision to SQLite + Excel
     i. If BET → send Telegram alert + open position
  5. Check open positions for exit conditions:
     - Winner positions: check profit target / edge flip
     - Non-winner positions: skip (hold to settlement)
     - Settled markets: auto-close at 100¢ or 0¢
```

## Environment Variables (.env)
| Variable | Description |
|---|---|
| `KALSHI_API_KEY` | Kalshi API key |
| `KALSHI_RSA_PRIVATE_KEY_PATH` | Path to RSA private key PEM |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token for alerts |
| `TELEGRAM_CHAT_ID` | Telegram chat ID for alerts |
| `DATAGOLF_API_KEY` | Data Golf Scratch Plus API key |
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude agent |
| `EDGE_THRESHOLD_PCT` | Min edge % to trigger alert (default: 10) |
| `POLL_INTERVAL_SEC` | Seconds between poll cycles (default: 60) |
| `ALERT_COOLDOWN_MIN` | Minutes before re-alerting same market (default: 30) |

## Key Thresholds
| Setting | Value | Location |
|---------|-------|----------|
| Min edge to evaluate | 8% | `main.py` `MIN_EDGE_TO_EVALUATE` |
| Max spread | 15¢ | `main.py` `MAX_SPREAD` |
| Name match cutoff | 0.6 | `main.py` `match_name()` |
| Max stake suggestion | 5% | `agent.py` prompt |
| Fallback BET threshold | 15% | `agent.py` `_fallback_decision()` |
| Profit exit target | +15¢ | `positions.py` (winner only) |
| Edge flip exit | -8% | `positions.py` (winner only) |
| Alert cooldown | 30 min | `config.py` `ALERT_COOLDOWN_MIN` |
| No-tournament sleep | 5 min | `main.py` `NO_TOURNAMENT_INTERVAL` |

## Position Management Strategy
- **Entry:** When agent returns BET, a position is opened at the yes_ask price
- **Winner markets:** Actively monitored for profit target (+15¢) or edge flip (-8%). Sell alerts sent via Telegram.
- **Top 5/10/20, Make Cut:** Held to settlement. No early exit. Market resolves at 100¢ (win) or 0¢ (loss).
- **Settled markets:** If a market disappears from active list, Kalshi API is checked for settlement status. Auto-closed at result price.

## Verified Working
- Data Golf API: returns 147 players (probabilities zeroed when no live tournament)
- Kalshi API: auth + market discovery across 5 series
- Telegram: alerts sending with HTML formatting, bid/ask/spread display
- Telegram commands: /positions and /stats
- Claude agent: evaluating opportunities with structured JSON responses
- Position tracking: open/close with P&L calculation
- Spread filter: skipping illiquid markets (logged in output)
- Excel logging: all decisions logged with full context

## Known Gaps
- **No automated tests**
- **No trade execution** — recommends only, doesn't place orders
- **No outcome tracking automation** — outcomes must be logged manually in Excel or via a separate script
- **Name matching** at 0.6 cutoff could produce false matches for similar names
- **Data Golf in-play endpoint** returns zeroed data between tournaments/rounds
- **Single-threaded evaluation** — each Claude call takes 3-4 seconds

## Next Steps
- Build outcome logging (scrape final results, update outcomes table)
- Add automated trade execution via Kalshi API
- Add Kelly criterion refinement to agent prompt
- Build a query CLI to review decision history from SQLite
