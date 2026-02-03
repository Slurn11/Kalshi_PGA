# PGA Golf Betting Agent — How It Works

## Overview
The bot polls every **60 seconds** during live tournaments, comparing Data Golf's statistical model against Kalshi market prices to find mispriced golfer outcomes. When it finds a meaningful edge in a liquid market, it asks Claude AI whether the bet is worth taking, then sends a Telegram recommendation with full context including bid/ask spread.

---

## Data Sources

### 1. Data Golf (datagolf_client.py)
- **API:** `feeds.datagolf.com/preds/in-play`
- **What it provides:** Live win probabilities for every golfer in the field
- **Markets covered:** win, top_5, top_10, top_20, make_cut
- **Format:** Decimal probabilities (0.0-1.0), converted to percentages internally
- **Name format:** "Last, First" — normalized to "First Last"
- **Also provides:** Leaderboard data (position, score to par, round, holes completed) cached from the same API call
- **Returns 0s when:** No live tournament or round hasn't started

### 2. Kalshi (kalshi_client.py)
- **Series searched:** KXPGATOUR, KXPGA, KXPGATOP5, KXPGATOP10, KXPGATOP20
- **Auth:** RSA-PSS signature (private key in kalshi_private_key.pem)
- **Market data model:** `KalshiMarket` dataclass in `models.py` — ticker, golfer_name, market_type, yes_ask, yes_bid, no_ask, no_bid
- **Liquidity filter:** Markets with `yes_bid = 0` are excluded (no one willing to buy = no real market)
- **Implied probability:** `yes_ask / 100` (e.g., yes_ask=35 means 35% implied — this is the price you'd pay to buy)
- **Status filter:** Only `open` or `active` markets
- **Rate limiting:** 200ms delay between series requests

### 3. Data Golf Leaderboard (datagolf_client.py)
- **Purpose:** Context for the AI agent — position, score to par, round, holes completed
- **Source:** Derived from the same Data Golf API fetch (no extra API call)
- **Not used for edge calculation** — purely informational for smarter decisions

### 4. ESPN Leaderboard (leaderboard.py)
- **Backup/alternative** leaderboard source from ESPN API
- **Parses:** Position, score to par, round number, holes completed
- **Handles:** CUT, WD, DQ, MDF statuses

---

## Edge Calculation

```
edge_pct = (data_golf_probability - kalshi_implied_probability) * 100
```

**Implied probability** = `yes_ask / 100` — this is what you'd actually pay, so it's the conservative measure.

**Example:**
- Data Golf says Scottie Scheffler has a 35% chance to finish top 5
- Kalshi yes_ask is 28 cents (28% implied)
- Edge = (0.35 - 0.28) * 100 = **+7.0%**

**Only positive edges matter** — we're looking for golfers that Data Golf thinks are underpriced on Kalshi.

---

## Filtering Pipeline

```
~60-110 Kalshi golf markets (winner + top5 + top10 + top20)
  → Filter: yes_bid > 0 (liquidity exists)
  → Match golfer name to Data Golf (fuzzy match, 60% similarity cutoff)
  → Calculate edge
  → Filter: edge >= 8% (MIN_EDGE_TO_EVALUATE)
  → Filter: spread <= 15¢ (MAX_SPREAD)
Only markets passing all filters get sent to Claude for evaluation
```

### Why 8% minimum edge?
Each Claude evaluation costs an API call (~3-4 seconds + money). Most small edges aren't actionable after accounting for Kalshi spreads and model uncertainty. 8% is the floor to even consider.

### Why 15¢ max spread?
Wide spreads indicate illiquid markets. If you buy at the ask and need to sell before settlement, you'd sell at the bid — losing the entire spread. A 15¢ cap ensures you're only entering markets where the bid/ask gap is reasonable. Markets exceeding this are logged as "Spread too wide" with the exact bid/ask values.

---

## Bid, Ask, and Spread Explained

- **Yes Ask:** The price to buy a Yes contract. This is what you pay to enter a position.
- **Yes Bid:** The price someone will pay for your Yes contract. This is what you'd get if you sold before settlement.
- **Spread:** Ask minus Bid. The cost of a round-trip (buy then sell) before settlement.

**Example:** Ask=62¢, Bid=50¢, Spread=12¢
- You pay 62¢ to enter
- If you sell immediately, you get 50¢ back (12¢ loss)
- If you hold to settlement: win = 100¢ (38¢ profit), lose = 0¢ (62¢ loss)

The most efficient outcome is **holding to settlement** — no spread cost on exit. Early selling is only worthwhile when the situation has changed significantly.

---

## AI Agent Evaluation (agent.py)

When an opportunity passes all filters, Claude (Sonnet) receives:

**Input:**
- Player name, market type (winner/top5/top10/top20/make_cut)
- Data Golf probability vs Kalshi implied probability
- Edge percentage
- Leaderboard context (position, score, round, holes played)
- Agent's own historical accuracy stats (from SQLite)
- Recent BET decisions for similar markets

**Output (structured JSON):**
```json
{
    "decision": "BET" | "PASS" | "WATCH",
    "confidence": 0.0-1.0,
    "suggested_stake_pct": 0.0-5.0,
    "reasoning": "2-4 sentence explanation"
}
```

**What the agent considers:**
- Is the edge large enough to be real after model error?
- What round is it? (Round 4 edges are more actionable than Round 1)
- Where is the golfer on the leaderboard?
- How has the agent performed historically on similar bets?
- Could this be a data/matching error?

**Fallback (if Claude API fails):**
- Edge >= 15% → BET with 0.5 confidence, 1% stake
- Otherwise → WATCH

---

## Decision Flow

```
Every 60 seconds:
  1. Check Telegram for commands (/positions, /stats)
  2. Fetch Data Golf live probabilities (147 players)
  3. Discover Kalshi markets across 5 series (~60-110 liquid markets)
  4. Build leaderboard from Data Golf data
  5. For each liquid Kalshi market:
     a. Fuzzy-match golfer name to Data Golf
     b. Look up the matching probability (win/top5/top10/top20/make_cut)
     c. Calculate edge
     d. If edge < 8% → skip
     e. If spread > 15¢ → skip (logged)
     f. If passes filters → log opportunity to SQLite
     g. Send to Claude agent with full context
     h. Claude returns BET / PASS / WATCH
     i. Log decision to SQLite + Excel
     j. If BET → send Telegram alert (30-min cooldown) + open position
  6. Check open positions for exit conditions:
     - Winner positions only: profit target (+15¢) or edge flip (-8%)
     - Non-winner positions: skip entirely (hold to settlement)
     - Settled/closed markets: auto-close position at result price
  7. Sleep 60 seconds (or 5 min if no live tournament data)
```

---

## Position Management (positions.py)

### Opening Positions
When the agent returns BET, a position is opened:
- **Entry price:** yes_ask (what you'd pay to buy)
- **Entry edge:** edge at time of entry
- **Status:** OPEN
- Duplicate tickers are rejected (UNIQUE constraint)

### Exit Strategy by Market Type

**Outright Winner (`winner`):**
- Actively monitored every cycle
- **Profit target:** Exit if yes_bid >= entry_price + 15¢
- **Edge flip:** Exit if current edge <= -8%
- Sell alert sent via Telegram with entry/exit prices and P&L

**All Other Markets (`top5`, `top10`, `top20`, `make_cut`):**
- **No early exit.** Held to settlement.
- Rationale: These markets are less liquid (wider spreads), so selling early means eating the spread for a guaranteed loss. Holding to settlement avoids spread cost — you either win 100¢ or lose your entry price.
- Positions auto-close when Kalshi settles the market (checked via API if market disappears from active list)

### P&L Tracking
- `profit_loss = exit_price - entry_price`
- Settlement: win = 100¢, loss = 0¢
- Stats available via `/stats` Telegram command: open count, closed count, win rate, total P&L, avg hold time

---

## Alert System (alerts.py)

**Channel:** Telegram (HTML-formatted messages)
**Cooldown:** 30 minutes per market ticker

### BET Recommendation Message Includes:
- Decision badge (BET RECOMMENDATION)
- Player name and market type
- Data Golf probability
- Kalshi ask price, bid price, and spread (e.g., `62¢ ask (50¢ bid) | Spread: 12¢`)
- Edge % and confidence %
- Suggested stake % of bankroll
- Leaderboard position, score, round
- Historical win rate (by market type and overall)
- Agent's reasoning

### Sell Alert (Winner Markets Only):
- Player name and market type
- Entry price → Exit price with P&L
- Exit reason (profit target or edge flip)

---

## Logging & Tracking

### SQLite (database.py → decisions.db)
Four tables:
- **opportunities** — every edge found (player, probabilities, edge, leaderboard context)
- **decisions** — agent's BET/PASS/WATCH + reasoning + confidence + stake suggestion
- **outcomes** — WIN/LOSS/PUSH (must be filled manually or via separate script)
- **positions** — open/closed positions with entry/exit prices, timestamps, P&L, status

Used by the agent itself to query past performance and inform future decisions.

### Excel (bet_logger.py → bet_log.xlsx)
Single spreadsheet with columns:
```
Timestamp | Tournament | Player | Market Type | Ticker |
DG Prob | Kalshi Implied | Edge % | Decision | Confidence |
Suggested Stake % | Reasoning | Position | Score | Round | Holes |
Outcome (manual) | P/L (manual)
```

Also provides `get_historical_stats()` for Telegram alerts — calculates win rate and P&L by market type from rows with filled outcomes.

---

## Telegram Commands (telegram_commands.py)

| Command | Response |
|---------|----------|
| `/positions` | Lists all open positions with player, market type, entry price, and edge |
| `/stats` | Shows aggregate stats: open/closed count, win rate, total realized P&L, avg hold time |

Commands are checked at the start of each polling cycle.

---

## Key Thresholds to Tune

| Setting | Current Value | Where | Notes |
|---------|--------------|-------|-------|
| Min edge to evaluate | 8% | `main.py` `MIN_EDGE_TO_EVALUATE` | Lower = more API calls but catches smaller edges |
| Max spread | 15¢ | `main.py` `MAX_SPREAD` | Higher = allows more illiquid markets |
| Poll interval | 60s | `.env` `POLL_INTERVAL_SEC` | How often to check for new edges |
| Alert cooldown | 30 min | `.env` `ALERT_COOLDOWN_MIN` | Per-market Telegram cooldown |
| Name match cutoff | 0.6 | `main.py` `match_name()` | Lower = more false matches, higher = missed matches |
| Max stake suggestion | 5% | `agent.py` prompt | Claude won't suggest more than 5% of bankroll |
| Fallback BET threshold | 15% | `agent.py` `_fallback_decision()` | Auto-BET if Claude API is down and edge >= 15% |
| Profit exit target | +15¢ | `positions.py` | Winner markets only |
| Edge flip exit | -8% | `positions.py` | Winner markets only |
| Liquidity filter | yes_bid > 0 | `kalshi_client.py` | Excludes markets with no buyers |
| No-tournament sleep | 5 min | `main.py` `NO_TOURNAMENT_INTERVAL` | Longer sleep when DG returns no data |

---

## Current Limitations

1. **No trade execution** — Bot recommends only, doesn't place orders on Kalshi.
2. **No automated outcome tracking** — WIN/LOSS must be filled manually in the Excel log or via a separate script.
3. **Name matching at 0.6 cutoff** — Could produce false matches for similar names (e.g., two players with similar last names).
4. **Data Golf returns 0s between rounds** — Bot sleeps 5 min and retries when no live data.
5. **Single-threaded evaluation** — Each Claude call takes 3-4 seconds; many edges in one cycle could be slow.
6. **Implied probability uses yes_ask** — This is the price to buy YES. The midpoint of yes_bid/yes_ask might be more accurate but less conservative.
7. **No automated tests** — System is validated by running live during tournaments.
