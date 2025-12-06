# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Whale Hunter** is a blockchain analytics system for detecting insider trading patterns and identifying "whale" wallets through on-chain forensics. The goal is to find wallets that consistently buy tokens early (before pumps) through **pattern detection** (NOT profitability analysis).

**Primary Target**: Ethereum/Base EVM chains
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
│   │ DEXScreener API  │    │ Google BigQuery │                  │
│   │ (Token Price)    │    │ (EVM Historical)│                  │
│   │                  │    │                 │                  │
│   │ • 10x tokens     │    │ • Ethereum      │                  │
│   │ • FREE API       │    │ • Token xfers   │                  │
│   │ • No auth        │    │ • First buyers  │                  │
│   └────────┬─────────┘    └────────┬────────┘                  │
│            │                       │                            │
│            └───────────┬───────────┘                            │
│                        ▼                                        │
│            ┌─────────────────────┐                             │
│            │   LOCAL ANALYSIS    │                             │
│            │                     │                             │
│            │  • DuckDB (storage) │                             │
│            │  • pandas (analysis)│                             │
│            │  • networkx (graph) │                             │
│            └──────────┬──────────┘                             │
│                       ▼                                         │
│            ┌─────────────────────┐                             │
│            │      OUTPUTS        │                             │
│            │                     │                             │
│            │  • Whale watchlist  │                             │
│            │  • Pattern reports  │                             │
│            │  • Score rankings   │                             │
│            └─────────────────────┘                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Critical Workflow: DEXScreener → BigQuery

**THE PROBLEM**: BigQuery alone cannot identify 10x tokens (transfer count ≠ profitability)

**THE SOLUTION**: Two-step pipeline

```
Step 1: DEXScreener API (FREE)
  ↓
  Find tokens with >500% 24h gains
  Filter by liquidity & volume
  ↓
  Output: List of actual 10x token addresses

Step 2: BigQuery (paid)
  ↓
  Search ONLY those specific tokens
  Find wallets in first 50 buyers
  ↓
  Output: Whale candidates
```

**See WORKFLOW.md for complete details**

---

## Tech Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Token Identification** | DEXScreener API | Identify actual 10x tokens (FREE) |
| **EVM Historical Data** | Google BigQuery | Query blockchain for early buyers |
| **Local Storage** | DuckDB + Parquet | Fast analytical queries locally |
| **Analysis** | pandas, numpy, scipy | Data manipulation, statistics |
| **Graph Analysis** | networkx | Wallet clustering, fund tracing |
| **HTTP Requests** | requests | DEXScreener API calls |

### Required Python Packages

```
duckdb>=0.9.0
pandas>=2.0.0
numpy>=1.24.0
scipy>=1.11.0
networkx>=3.1
google-cloud-bigquery>=3.11.0
pyarrow>=12.0.0
python-dotenv>=1.0.0
requests>=2.31.0
```

---

## Current Project Structure

```
whale-hunter/
├── CLAUDE.md                   # This file
├── README.md                   # User-facing documentation
├── WORKFLOW.md                 # Complete pipeline workflow
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
│   │   ├── dexscreener_client.py  # DEXScreener API (NEW)
│   │   └── storage.py          # DuckDB schema & operations
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── wallet_metrics.py   # Basic metrics (NO win rates)
│   │   ├── early_buyer.py      # Early buying pattern analysis
│   │   └── clustering.py       # Wallet network analysis
│   ├── detection/
│   │   ├── __init__.py
│   │   ├── patterns.py         # 4 suspicious patterns
│   │   └── scorer.py           # Whale score (0-100)
│   └── utils/
│       ├── __init__.py
│       └── helpers.py
├── queries/
│   └── ethereum/
│       ├── first_buyers.sql    # Find early buyers (uses @successful_token_addresses param)
│       └── wallet_history.sql  # Get buy transaction history
├── data/
│   ├── exports/                # Parquet exports
│   ├── whales.db              # DuckDB database
│   └── .gitkeep
├── scripts/
│   ├── 01_fetch_historical.py # DEXScreener → BigQuery → DuckDB
│   └── 02_analyze_wallets.py  # Analyze & score candidates
└── notebooks/
    └── exploration.ipynb       # Ad-hoc analysis
```

**Note**: Files like `helius_client.py`, `timing.py`, `token_performance.sql` were removed as they are not needed for the current implementation.

---

## Core Detection Strategy

### NO Win Rate Calculation

**IMPORTANT**: We DO NOT calculate win rates or profitability. This is impossible to do accurately.

Instead, we use **pattern matching**:
- Early buying patterns
- Sniping behavior
- Wallet clustering
- Timing analysis

### 4 Suspicious Patterns (Severity 1-5)

```python
# src/detection/patterns.py

1. CONSISTENT_EARLY_BUYER (Severity 5)
   - Avg buy rank ≤ 20
   - 5+ early hits on 10x tokens

2. LIQUIDITY_SNIPER (Severity 5)
   - 3+ same-block buys
   - Bought in same block as liquidity add

3. FRESH_WALLET_ALPHA (Severity 4)
   - Wallet age < 7 days
   - Immediately starts sniping (2+ early hits)

4. WALLET_CLUSTER (Severity 4)
   - Part of 5+ wallet cluster
   - Common funding source (Sybil attack indicator)
```

**Removed patterns**:
- `HIGH_WIN_RATE` - We don't calculate win rates
- `PRECISE_EXIT` - We don't track sells
- `HIGH_VOLUME_EARLY` - We don't track volume (removed value_eth)

### Whale Score (0-100)

```python
# src/detection/scorer.py

Score = Early Hit Score (0-50)
      + Buy Rank Score (0-30)
      + Pattern Severity (0-20)

Thresholds:
- 60+: Add to watchlist
- 80+: High-priority whale (likely insider)
```

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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Trades table (BUY transactions only)
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY,
    wallet VARCHAR NOT NULL,
    chain VARCHAR NOT NULL,
    token_address VARCHAR NOT NULL,
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

-- Tokens, patterns, clusters, watchlist tables...
-- (See storage.py for complete schema)
```

**Key changes from examples**:
- NO `value_eth` column (we don't track volume)
- NO `action` column (only BUYs, no sells)
- NO `win_rate` column (we don't calculate profitability)
- Added `launch_timestamp`, `launch_block` (from BigQuery)
- Added timing columns for pattern detection

---

## BigQuery Queries

### 1. first_buyers.sql

**Purpose**: Find wallets that were early buyers on 10x tokens

**Key feature**: Accepts `@successful_token_addresses` parameter (from DEXScreener)

```sql
-- Simplified structure
WITH successful_tokens AS (
    -- Token addresses from DEXScreener API
    SELECT token_address
    FROM UNNEST(@successful_token_addresses) AS token_address
),

first_buy_per_wallet AS (
    -- Get first buy for each wallet-token pair
    SELECT wallet, token_address, MIN(block_timestamp) AS first_buy
    FROM token_transfers
    GROUP BY wallet, token_address
),

ranked_buyers AS (
    -- Rank buyers by entry time
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY token_address
        ORDER BY first_buy ASC
    ) AS buy_rank
    FROM first_buy_per_wallet
)

SELECT wallet, COUNT(*) AS early_hit_count
FROM ranked_buyers
WHERE buy_rank <= 50  -- First 50 buyers
GROUP BY wallet
HAVING early_hit_count >= 5  -- At least 5 early hits
```

### 2. wallet_history.sql

**Purpose**: Get detailed buy transaction history for candidates

**Cost optimization**: Removed expensive `traces` table join for ETH values

```sql
-- Returns: wallet, token_address, buy_rank, timestamp,
--          is_same_block_buy, seconds_after_launch, etc.
-- NO value_eth column (not needed, saves 50% on query cost)
```

---

## DEXScreener API Client

```python
# src/data/dexscreener_client.py

from src.data.dexscreener_client import DEXScreenerClient

client = DEXScreenerClient()

# Get 10x tokens (FREE, no auth required)
tokens = client.find_10x_tokens(
    chain="ethereum",
    min_return_multiple=10.0
)

# Returns DataFrame with:
# - token_address
# - symbol
# - price_change_24h (used as proxy for 10x)
# - liquidity_usd
# - volume_24h
```

**Limitations**:
- Uses 24h price change as proxy (not perfect)
- Tokens with >500% 24h gain likely did 10x over longer period
- For production, consider Dune Analytics for historical data

---

## Execution Scripts

### 01_fetch_historical.py

**Complete workflow**:

1. Initialize DuckDB
2. Connect to BigQuery
3. **Call DEXScreener API** → Get 10x tokens
4. Save successful_tokens.csv
5. Pass token list to BigQuery via parameter
6. Execute first_buyers.sql → Get whale candidates
7. Execute wallet_history.sql → Get trade details
8. Load into DuckDB

**Cost**: ~$0.25-0.50 (50% cheaper after removing value_eth)

### 02_analyze_wallets.py

**Workflow**:

1. Load candidates from DuckDB
2. For each wallet:
   - Calculate basic metrics (wallet_metrics.py)
   - Analyze early buying (early_buyer.py)
   - Detect patterns (patterns.py)
   - Calculate whale score (scorer.py)
3. Update database with scores
4. Add high scorers (≥60) to watchlist
5. Generate whale_report.csv

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

Already implemented in:
- `wallet_metrics.py`
- `early_buyer.py`

### 2. BigQuery Cost Control

**ALWAYS estimate before executing**:

```python
from src.data.bigquery_client import BigQueryClient

bq = BigQueryClient()

# Dry run (FREE)
estimate = bq.estimate_query_cost(sql)
print(f"Will scan {estimate['gb_scanned']:.2f} GB (${estimate['cost_usd']:.4f})")

# Only execute if acceptable
if estimate['cost_usd'] < 0.10:
    results = bq.query(sql)
```

### 3. No Unnecessary Features

**Removed** to reduce complexity and cost:
- Win rate calculation (impossible to do accurately)
- Volume tracking (value_eth) - saves 50% on BigQuery costs
- Sell tracking (we only care about buys)
- token_performance.sql (replaced by DEXScreener API)

### 4. Pattern Detection Focus

Track **THAT** they were early, not **HOW MUCH** they spent:
- Early hit count
- Average buy rank
- Same-block buys
- Timing patterns
- Wallet clustering

---

## Configuration

```python
# config/settings.py - KEY SETTINGS

# Detection Thresholds
MIN_EARLY_HITS = 5           # Min early hits to be considered
FIRST_N_BUYERS = 50          # First N buyers are "early"
MIN_TOKEN_RETURN_MULTIPLE = 10.0  # 10x return requirement
LOOKBACK_DAYS = 180          # 6 months of data

# Pattern Detection
LIQUIDITY_SNIPER_MIN_HITS = 3     # Min same-block buys
FRESH_WALLET_DAYS = 7             # New wallet threshold
CLUSTER_MIN_SIZE = 5              # Min wallets in cluster
EARLY_BUYER_AVG_RANK_THRESHOLD = 20  # Avg rank for pattern

# Whale Score
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
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your BigQuery credentials

# 3. Run pipeline
python scripts/01_fetch_historical.py  # DEXScreener → BigQuery
python scripts/02_analyze_wallets.py   # Analyze & score

# 4. Check results
# - data/successful_tokens.csv (10x tokens from DEXScreener)
# - data/first_buyers.parquet (whale candidates)
# - data/whale_report.csv (scored whales)
# - data/whales.db (DuckDB with all data)
```

---

## Important Rules for Claude Code

1. **Never calculate win rates** - Pattern matching only
2. **Always use DuckDB** for local queries - No PostgreSQL
3. **Always estimate BigQuery costs** before running queries
4. **Use DEXScreener for token identification** - Don't try to find 10x tokens in BigQuery
5. **Copy DataFrames** before mutation
6. **Track early buying patterns** - Not profitability
7. **Keep it simple** - Remove unused features
8. **Parquet over CSV** - Faster and smaller
9. **No unnecessary clutter** - Archive old experiments

---

## Cost Breakdown

| Component | Cost | Notes |
|-----------|------|-------|
| DEXScreener API | FREE | No authentication required |
| BigQuery (1st run) | $0.25-0.50 | ~50-100 GB scanned |
| BigQuery (subsequent) | $0.10-0.25 | Smaller queries |
| DuckDB | FREE | Local storage |
| **Total MVP** | ~$0.50 | One-time setup |

---

## Future Enhancements (Not Yet Implemented)

- Solana integration (Helius API)
- Real-time monitoring
- Telegram alerts
- Web dashboard
- Backtesting framework
- Copy trading automation

**Current Status**: MVP focused on Ethereum/Base historical analysis

---

## Documentation Files

- **CLAUDE.md** (this file): Technical reference for Claude Code
- **README.md**: User-facing setup guide
- **WORKFLOW.md**: Complete pipeline documentation with diagrams
- **requirements.txt**: Python dependencies
- **.env.example**: Environment variable template

---

## Key Takeaways

✅ **Pattern detection, not profitability**
✅ **DEXScreener → BigQuery pipeline**
✅ **Cost-optimized (removed expensive features)**
✅ **4 patterns, 0-100 score**
✅ **No win rates, no volume tracking**
✅ **FREE token identification via DEXScreener**
✅ **~$0.50 total cost for MVP**
