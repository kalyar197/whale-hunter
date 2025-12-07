# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Whale Hunter** is a blockchain analytics system for detecting insider trading patterns and identifying "whale" wallets through on-chain forensics. The goal is to find wallets that consistently buy tokens early (before pumps) through **pattern detection** (NOT profitability analysis).

**Current Status**: Ethereum mainnet analysis working with pattern detection enabled
**Future Target**: Solana memecoins (via Helius API)

**Key Principle**: We track THAT wallets were early, not HOW MUCH they made. No win rates, no profitability calculations - pure pattern matching.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌──────────────────┐    ┌─────────────────┐                  │
│   │ Dune Analytics   │    │ Google BigQuery │                  │
│   │ (Token Discovery)│    │ (EVM Historical)│                  │
│   │                  │    │                 │                  │
│   │ • 4x+ tokens     │    │ • Ethereum      │                  │
│   │ • 365-day data   │    │ • Token xfers   │                  │
│   │ • Manual export  │    │ • First buyers  │                  │
│   └────────┬─────────┘    └────────┬────────┘                  │
│            │                       │                            │
│            └───────────┬───────────┘                            │
│                        ▼                                        │
│            ┌─────────────────────┐                             │
│            │   LOCAL ANALYSIS    │                             │
│            │                     │                             │
│            │  • DuckDB (storage) │                             │
│            │  • pandas (analysis)│                             │
│            │  • Pattern detect   │                             │
│            └──────────┬──────────┘                             │
│                       ▼                                         │
│            ┌─────────────────────┐                             │
│            │      OUTPUTS        │                             │
│            │                     │                             │
│            │  • Master list (ALL)│                             │
│            │  • Watchlist (top)  │                             │
│            │  • Pattern reports  │                             │
│            └─────────────────────┘                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Core Detection Strategy

### NO Win Rate Calculation

**IMPORTANT**: We DO NOT calculate win rates or profitability. This is impossible to do accurately.

Instead, we use **pattern matching**:
- Early buying patterns
- Sniping behavior
- Buy rank consistency
- Timing analysis
- Precision filtering (early hits / total activity)

### 2 Key Patterns Detected (Severity 2-5)

```python
# src/detection/patterns.py

1. CONSISTENT_EARLY_BUYER (Severity 5)
   - Avg buy rank ≤ 20
   - 5+ early hits on 4x+ tokens

2. LIQUIDITY_SNIPER (Severity 2 or 5) - CONTEXT-AWARE
   - Fresh wallet (< 7 days) + 3+ same-block buys = Severity 5 (INSIDER)
   - Old wallet + 3+ same-block buys = Severity 2 (MEV bot noise)
```

**Note**: Other patterns (FRESH_WALLET_ALPHA, WALLET_CLUSTER, STRATEGIC_DUMPER) are defined but currently disabled pending additional data sources.

### Whale Score (0-100) with Logarithmic Scaling

```python
# src/detection/scorer.py - LOGARITHMIC SCORING

Component 1: Early Hit Score (0-50 points) - LOGARITHMIC
  score = 50 * log(1 + early_hits) / log(1 + 20)
  # Smooth scaling with diminishing returns
  # 1 hit = ~10 points, 5 hits = ~32, 10 hits = ~43, 20 hits = 50

Component 2: Buy Rank Score (0-30 points) - LOGARITHMIC
  score = 30 * (1 - log(rank) / log(100))
  # Rank 1 = 30 pts, Rank 10 = ~21 pts, Rank 50 = ~11 pts

Component 3: Pattern Severity (0-20 points)
  score = min(total_severity * 4, 20)

Base Score = Early Hit Score + Buy Rank Score + Pattern Severity

Component 4: Precision Penalty (CRITICAL) - LOGARITHMIC APPLICATION
  Final Score = Base Score × score_penalty (0.2 to 1.0)

  Precision Penalty:
  - Precision < 1% + 500+ tokens: 0.2 (80% penalty)
  - Precision < 5% + 200+ tokens: 0.5 (50% penalty)
  - Precision < 10% + 100+ tokens: 0.7 (30% penalty)
  - Otherwise: 1.0 (no penalty)

Thresholds:
- 60+: Watchlist tier (high confidence)
- 40-59: High priority monitoring
- 20-39: Medium priority
- <20: Low priority
```

**Key improvements**:
- **Logarithmic scoring** for early hits and buy rank (no arbitrary cliffs)
- Precision penalty filters spray-and-pray bots
- Mathematically justified with smooth diminishing returns
- Pattern detection adds 8-20 points for confirmed behavior

---

## Current Project Structure

```
whale-hunter/
├── CLAUDE.md                   # This file
├── README.md                   # User-facing documentation
├── requirements.txt
├── .env.example
├── .gitignore
├── config/
│   ├── __init__.py
│   └── settings.py             # Configuration & thresholds
├── src/
│   ├── __init__.py
│   ├── data/
│   │   ├── __init__.py
│   │   ├── bigquery_client.py  # BigQuery + dry-run cost estimator
│   │   ├── geckoterminal_client.py  # GeckoTerminal API (backup)
│   │   └── storage.py          # DuckDB schema & operations
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── wallet_metrics.py   # Basic metrics (NO win rates)
│   │   └── early_buyer.py      # Early buying pattern analysis
│   ├── detection/
│   │   ├── __init__.py
│   │   ├── patterns.py         # 2 active patterns (5 total defined)
│   │   └── scorer.py           # Whale score (0-100)
│   └── utils/
│       ├── __init__.py
│       └── helpers.py
├── queries/
│   └── ethereum/
│       ├── first_buyers_simple.sql    # Find early buyers (simplified)
│       ├── wallet_history_simple.sql  # Get trade history (simplified)
│       └── wallet_activity.sql        # Get total activity (precision calc)
├── data/
│   ├── master_whale_list.csv  # ** MASTER LIST - ALL WALLETS **
│   ├── watchlist.csv          # Filtered view (score >= 40)
│   ├── successful_tokens.csv  # Input: tokens to analyze
│   ├── whales.db              # DuckDB database
│   └── exports/               # BigQuery results (parquet)
│       ├── first_buyers.parquet
│       ├── wallet_history.parquet
│       ├── wallet_activity.parquet
│       ├── token_launches.parquet
│       └── successful_tokens.csv
├── scripts/
│   ├── 01_fetch_historical.py # Dune/GeckoTerminal → BigQuery → DuckDB
│   └── 02_analyze_wallets.py  # Analyze & score candidates
├── create_watchlist.py        # Utility: regenerate watchlist from master
└── notebooks/
    └── exploration.ipynb       # Ad-hoc analysis
```

**Key Files**:
- **`data/master_whale_list.csv`** - ALL wallets ever tested (97 currently)
- **`data/watchlist.csv`** - Filtered view of top wallets (7 currently, score ≥ 40)
- **`data/successful_tokens.csv`** - Input tokens from Dune/GeckoTerminal

---

## Master Whale List System

### How It Works

**Every analysis run adds ALL wallets to the master list:**
1. Run `01_fetch_historical.py` → gets BigQuery data
2. Run `02_analyze_wallets.py` → scores all wallets
3. Results auto-merge into `master_whale_list.csv`
4. Duplicates deduplicated (keeps highest score per wallet+chain)

**Master list columns**:
```
wallet, chain, whale_score, early_hit_count, avg_buy_rank, best_buy_rank,
precision_rate, total_unique_tokens, pattern_count, patterns, base_score,
score_penalty, data_source, analysis_date, token_count, lookback_days
```

**Watchlist** is just a filtered view (score ≥ 40). Regenerate anytime:
```bash
python create_watchlist.py
```

### Adding New Analysis Runs

When running with Helius, Solana, or different timeframes:

```python
# After running 02_analyze_wallets.py, merge results:
import pandas as pd
from datetime import datetime

# Load new results
new = pd.read_csv('data/whale_report.csv')
new['chain'] = 'solana'  # or 'ethereum', 'base', etc.
new['data_source'] = 'helius'  # or 'dune', 'geckoterminal'
new['analysis_date'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# Load master and combine ALL wallets
master = pd.read_csv('data/master_whale_list.csv')
combined = pd.concat([master, new], ignore_index=True)

# Deduplicate (keep highest score per wallet+chain)
combined = combined.sort_values('whale_score', ascending=False)
combined = combined.drop_duplicates(subset=['wallet', 'chain'], keep='first')

# Save ALL wallets
combined.to_csv('data/master_whale_list.csv', index=False)
print(f'Master list: {len(combined)} total wallets')
```

**YOU decide which wallets matter at the end, not the system.**

---

## Data Schema (DuckDB)

```python
# src/data/storage.py - ACTUAL IMPLEMENTATION

-- Wallets table
CREATE TABLE IF NOT EXISTS wallets (
    address VARCHAR PRIMARY KEY,
    chain VARCHAR NOT NULL,
    first_seen TIMESTAMP,
    last_seen TIMESTAMP,
    total_trades INTEGER DEFAULT 0,
    early_hit_count INTEGER DEFAULT 0,
    avg_buy_rank FLOAT,
    whale_score FLOAT,
    cluster_id INTEGER,
    tags VARCHAR[],
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Trades table (BUY transactions only currently)
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY,
    wallet VARCHAR NOT NULL,
    chain VARCHAR NOT NULL,
    token_address VARCHAR NOT NULL,
    action VARCHAR NOT NULL CHECK(action IN ('BUY', 'SELL')),
    amount DOUBLE,
    timestamp TIMESTAMP NOT NULL,
    block_number BIGINT NOT NULL,
    tx_hash VARCHAR NOT NULL,
    tx_index INTEGER,
    buy_rank INTEGER,
    launch_timestamp TIMESTAMP,
    launch_block BIGINT,
    is_same_block_buy BOOLEAN DEFAULT FALSE,
    seconds_after_launch DOUBLE,
    blocks_after_launch INTEGER,
    FOREIGN KEY (wallet) REFERENCES wallets(address)
);
```

**Note**: Database currently stores trades for analysis but final results are exported to CSV for flexibility.

---

## BigQuery Queries (Simplified - No LP Detection)

### 1. first_buyers_simple.sql

**Purpose**: Find wallets that were early buyers on 4x+ tokens

**How it works**:
- Uses first token transfer as launch proxy (not actual LP creation)
- Ranks buyers from first transfer timestamp
- Expands to top 100 buyers per token (catches stealth insiders)

```sql
-- Simplified structure
WITH token_first_transfer AS (
    -- Get first transfer timestamp for each token (proxy for launch)
    SELECT token_address, MIN(block_timestamp) AS first_transfer_time
    FROM token_transfers
    WHERE token_address IN @successful_token_addresses
    GROUP BY token_address
),

ranked_buyers AS (
    -- Rank buyers from first transfer
    SELECT wallet, token_address, buy_rank
    FROM first_buy_per_wallet
    ORDER BY first_buy_time ASC
)

SELECT wallet, COUNT(*) AS early_hit_count
FROM ranked_buyers
WHERE buy_rank <= 100  -- First 100 buyers
GROUP BY wallet
HAVING early_hit_count >= 5  -- At least 5 early hits
```

**Parameters**:
- `@successful_token_addresses`: Token list from Dune/GeckoTerminal
- `@lookback_days`: Days to look back (default 180)
- `@min_early_hits`: Minimum early hits (default 5)

---

### 2. wallet_history_simple.sql

**Purpose**: Get detailed trade history for pattern detection

**CRITICAL**: No traces join (expensive). No ETH value filtering.

```sql
-- Returns: wallet, token_address, buy_rank, timestamp,
--          is_same_block_buy, seconds_after_launch, etc.

WITH wallet_buys AS (
    -- Get all buys (FILTER BY TOKEN FIRST - reduces scan cost)
    SELECT tt.to_address AS wallet, tt.token_address, tt.timestamp, ...
    FROM token_transfers tt
    WHERE tt.token_address IN @successful_token_addresses  -- CRITICAL
      AND tt.to_address IN @wallet_addresses
),

ranked_buys AS (
    -- Calculate buy rank from first transfer
    SELECT wb.*, ROW_NUMBER() OVER (
        PARTITION BY wb.token_address
        ORDER BY wb.timestamp ASC
    ) AS buy_rank
    FROM wallet_buys wb
)
```

**Cost**: ~$7-8 for 97 wallets (removed expensive traces table join)

**Parameters**:
- `@successful_token_addresses`: Token list (CRITICAL - reduces scan)
- `@wallet_addresses`: Candidate wallets
- `@lookback_days`: Days to look back
- `@min_whale_buy_eth`: Disabled (0.0) - no ETH filtering

---

### 3. wallet_activity.sql

**Purpose**: Get TOTAL wallet activity to calculate precision rate

**Why critical**: Filters out spray-and-pray bots that buy every token

```sql
-- For each candidate wallet:
-- Returns: total_unique_tokens, total_tx_count, activity_span_days
--
-- Used to calculate:
-- precision_rate = successful_tokens / total_unique_tokens
--
-- Example:
-- - Wallet A: 6 hits / 36 total tokens = 16.7% precision (SIGNAL)
-- - Wallet B: 5 hits / 5000 total tokens = 0.1% precision (NOISE - 80% penalty)
```

**Impact**: Eliminates ~74% of false positives by downgrading spray-and-pray bots

---

## GeckoTerminal API Client (Backup Token Discovery)

```python
# src/data/geckoterminal_client.py

from src.data.geckoterminal_client import GeckoTerminalClient

client = GeckoTerminalClient()

# Get ALL tokens with 4x+ gains (including pump-and-dumps)
tokens = client.find_4x_tokens(
    network="eth",
    min_return_multiple=4.0
)

# Returns DataFrame with:
# - token_address
# - symbol, name
# - price_change_24h (>= 300% = 4x gain)
# - liquidity_usd, volume_24h
# - pair_created_at
```

**Why this works**:
- Pump-and-dump insiders are who we're hunting
- Activity density filtering eliminates spray-and-pray bots
- Precision rate separates signal from noise

**API Details**:
- FREE GeckoTerminal API, no authentication required
- 30 calls per minute rate limit

**Currently**: Using Dune Analytics for token discovery (365-day lookback)

---

## Execution Scripts

### 01_fetch_historical.py

**Complete workflow**:

1. Initialize DuckDB
2. Connect to BigQuery
3. Load `data/successful_tokens.csv` (from Dune or GeckoTerminal)
4. Execute `first_buyers_simple.sql` → Get whale candidates (rank 1-100)
5. Execute `wallet_history_simple.sql` → Get trade details
6. Execute `wallet_activity.sql` → Get total activity (CRITICAL for precision)
7. Load all data into DuckDB
8. Export parquet files

**Cost**: ~$8-10 for 97 wallets (500 tokens, 365-day lookback)

**Query cost breakdown**:
- first_buyers_simple.sql: ~$0.20
- wallet_history_simple.sql: ~$7.50
- wallet_activity.sql: ~$2.00

### 02_analyze_wallets.py

**Workflow**:

1. Load candidates from DuckDB
2. Load activity density data (wallet_activity.parquet)
3. For each wallet:
   - Calculate basic metrics (wallet_metrics.py)
   - Analyze early buying (early_buyer.py)
   - Calculate precision_rate (early_hits / total_unique_tokens)
   - Detect patterns (patterns.py) - CONSISTENT_EARLY_BUYER, LIQUIDITY_SNIPER
   - Calculate whale score (scorer.py) - with precision penalty applied
4. Export to `data/whale_report.csv` (temporary - gets merged into master)
5. Master list auto-merge logic runs

**Output**:
- Whale score (with precision penalty)
- Early hits, avg buy rank
- Precision rate
- Pattern count and names
- Base score and score penalty

---

## Configuration

```python
# config/settings.py - KEY SETTINGS

# Detection Thresholds
MIN_EARLY_HITS = 5           # Min early hits to be considered
FIRST_N_BUYERS = 100         # First N buyers are "early"
MIN_TOKEN_RETURN_MULTIPLE = 4.0  # 4x return requirement (lowered from 10x)
LOOKBACK_DAYS = 180          # 6 months of data
MIN_WHALE_BUY_ETH = 0.0      # Disabled (was 0.1) - no ETH filtering

# Pattern Detection
LIQUIDITY_SNIPER_MIN_HITS = 3     # Min same-block buys
FRESH_WALLET_DAYS = 7             # New wallet threshold (disabled)
CLUSTER_MIN_SIZE = 5              # Min wallets in cluster (disabled)
EARLY_BUYER_AVG_RANK_THRESHOLD = 20  # Avg rank for pattern
STRATEGIC_DUMPER_MIN_EXITS = 3    # Min strategic exits (disabled)

# Whale Score (logarithmic scoring)
WHALE_SCORE_WATCHLIST = 60.0  # Watchlist threshold
WHALE_SCORE_ALERT = 80.0      # High-priority threshold

# BigQuery Cost Control
BIGQUERY_WARN_THRESHOLD_GB = 10.0  # Warn if >10 GB
BIGQUERY_COST_PER_TB = 5.0         # $5 per TB
```

---

## Environment Variables

```bash
# .env (required)
BIGQUERY_PROJECT=your_gcp_project_id
GOOGLE_APPLICATION_CREDENTIALS=C:\path\to\service-account.json

# Optional (for future features)
HELIUS_API_KEY=your_helius_key  # For Solana analysis
```

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your BigQuery credentials

# 3. Get token list (option A: Dune Analytics)
# - Run Dune query: https://dune.com/queries/...
# - Export to CSV as data/successful_tokens.csv

# 3. Get token list (option B: GeckoTerminal API)
python -c "
from src.data.geckoterminal_client import GeckoTerminalClient
client = GeckoTerminalClient()
tokens = client.find_4x_tokens('eth', min_return_multiple=4.0)
tokens.to_csv('data/successful_tokens.csv', index=False)
"

# 4. Run pipeline
python scripts/01_fetch_historical.py  # BigQuery → DuckDB (~$8-10)
python scripts/02_analyze_wallets.py   # Analyze & score

# 5. Check results
# - data/master_whale_list.csv (ALL wallets - 97 currently)
# - data/watchlist.csv (top wallets - 7 currently)

# 6. Regenerate watchlist anytime
python create_watchlist.py
```

---

## Important Implementation Notes

### 1. DataFrame Immutability

**ALWAYS copy DataFrames before modification**:

```python
# GOOD
def process(df: pd.DataFrame):
    df = df.copy()  # ✅
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df

# BAD
def process(df: pd.DataFrame):
    df['timestamp'] = pd.to_datetime(df['timestamp'])  # ❌ Mutates input
    return df
```

### 2. BigQuery Cost Control

**ALWAYS estimate before executing**:

```python
from src.data.bigquery_client import BigQueryClient

bq = BigQueryClient()

# Dry run (FREE)
estimate = bq.estimate_query_cost(sql)
print(f"Will scan {estimate['gb_scanned']:.2f} GB (${estimate['cost_usd']:.4f})")

# Only execute if acceptable
if estimate['cost_usd'] < 10.00:
    results = bq.query(sql)
```

### 3. No Unnecessary Features

**Removed** to reduce complexity and cost:
- LP creation detection (token_launches.sql) - too complex, 24-48h lag issues
- ETH value tracking (traces table join) - too expensive ($192 → $8 savings)
- Win rate calculation (impossible to do accurately)
- Sell tracking (wallet_sells.sql) - requires additional data sources

**What remains**:
- Buy rank from first transfer (simple, cheap)
- Pattern detection (CONSISTENT_EARLY_BUYER, LIQUIDITY_SNIPER)
- Precision filtering (eliminates 74% of false positives)
- Logarithmic scoring (mathematically justified)

---

## Cost Breakdown

| Component | Cost | Notes |
|-----------|------|-------|
| GeckoTerminal API | FREE | No authentication required |
| Dune Analytics | FREE | Manual export |
| BigQuery - first_buyers_simple.sql | $0.20 | ~40 GB |
| BigQuery - wallet_history_simple.sql | $7.50 | ~1.5 TB (no traces join) |
| BigQuery - wallet_activity.sql | $2.00 | ~400 GB |
| DuckDB | FREE | Local storage |
| **Total per run** | ~$9.70 | 500 tokens, 97 wallets, 365-day lookback |

**Cost optimization**:
- Removed traces table join ($192 → $8 savings)
- Filter by token FIRST in wallet_history_simple.sql (critical)
- No LP detection (complex + expensive)

---

## Current Analysis Results (Dec 2024)

**Data source**: Dune Analytics (500 tokens, 365-day lookback)
**Wallets analyzed**: 97
**Pattern detection**: ENABLED

### Score Distribution
- **70-79**: 1 wallet (TOP WHALE)
- **50-59**: 2 wallets
- **40-49**: 4 wallets (watchlist tier 2)
- **30-39**: 8 wallets
- **<30**: 82 wallets

### Top Whale
```
0xbde7ad38a4414e3e30a93dc39e2daf86a3b01653
Score: 72.7/100
Early Hits: 6
Avg Buy Rank: 4.1
Precision: 16.7% (6/36 tokens)
Patterns: CONSISTENT_EARLY_BUYER, LIQUIDITY_SNIPER
```

**Why this scores high**:
- **TOP 5 buyer** on average (rank 4.1)
- **High precision** (16.7% - no penalty)
- **2 patterns detected** (+8-10 points)
- Clean signal, not spray-and-pray bot

---

## Future Enhancements (Not Yet Implemented)

- Solana integration (Helius API)
- Sell behavior tracking (strategic dumper detection)
- Wallet clustering (Sybil attack detection)
- Fresh wallet detection (new wallet + immediate sniping)
- Real-time monitoring
- Telegram alerts
- Web dashboard

**Current Status**: MVP focused on Ethereum historical analysis with master list tracking

---

## Important Rules for Claude Code

1. **Never calculate win rates** - Pattern matching only
2. **Always use DuckDB** for local queries - No PostgreSQL
3. **Always estimate BigQuery costs** before running queries
4. **Filter by token FIRST** in wallet queries - Critical for cost control
5. **Copy DataFrames** before mutation
6. **Track early buying patterns** - Not profitability
7. **ALL wallets go to master list** - User decides what matters
8. **Keep it simple** - Remove unused features
9. **Parquet for exports, CSV for master list** - Best of both worlds
10. **No unnecessary clutter** - Delete temporary files

---

## Key Takeaways

✅ **Pattern detection, not profitability**
✅ **Dune/GeckoTerminal → BigQuery → Master List pipeline**
✅ **Precision rate filtering (CRITICAL for eliminating false positives)**
✅ **2 active patterns (CONSISTENT_EARLY_BUYER, LIQUIDITY_SNIPER), 0-100 score**
✅ **No win rates, no volume tracking, no LP detection**
✅ **ALL wallets tracked in master_whale_list.csv**
✅ **~$10 per run (500 tokens, 97 wallets, 365 days)**
✅ **Top whale: 72.7 points, 16.7% precision, rank 4.1 avg**
