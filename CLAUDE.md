# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Whale Hunter** is a blockchain analytics system for detecting insider trading patterns and identifying "whale" wallets through on-chain forensics. The goal is to find wallets that consistently buy tokens early (before pumps) with abnormally high win rates.

**Primary Target**: Solana memecoins (pump.fun, Raydium launches)
**Secondary Target**: Ethereum/Base memecoins

---

## Architecture
```
┌─────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌─────────────────┐         ┌─────────────────┐              │
│   │  Google BigQuery │         │   Helius API    │              │
│   │  (EVM Historical)│         │ (Solana Live)   │              │
│   │                 │         │                 │              │
│   │  • Ethereum     │         │  • Parsed TXs   │              │
│   │  • Polygon      │         │  • DAS API      │              │
│   │  • Token xfers  │         │  • Webhooks     │              │
│   └────────┬────────┘         └────────┬────────┘              │
│            │                           │                        │
│            └─────────────┬─────────────┘                        │
│                          ▼                                      │
│              ┌─────────────────────┐                           │
│              │   LOCAL ANALYSIS    │                           │
│              │                     │                           │
│              │  • DuckDB (storage) │                           │
│              │  • pandas (analysis)│                           │
│              │  • networkx (graph) │                           │
│              └──────────┬──────────┘                           │
│                         ▼                                       │
│              ┌─────────────────────┐                           │
│              │      OUTPUTS        │                           │
│              │                     │                           │
│              │  • Whale watchlist  │                           │
│              │  • Telegram alerts  │                           │
│              │  • Analysis reports │                           │
│              └─────────────────────┘                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| EVM Historical Data | Google BigQuery | Query TB-scale blockchain data |
| Solana Data | Helius API | Real-time + parsed transactions |
| Local Storage | DuckDB + Parquet | Fast analytical queries locally |
| Analysis | pandas, numpy, scipy | Data manipulation, statistics |
| Graph Analysis | networkx | Wallet clustering, fund tracing |
| Alerts | python-telegram-bot | Real-time notifications |

### Required Python Packages

```
duckdb>=0.9.0
pandas>=2.0.0
numpy>=1.24.0
scipy>=1.11.0
networkx>=3.1
google-cloud-bigquery>=3.11.0
python-telegram-bot>=20.0
httpx>=0.24.0
aiohttp>=3.8.0
solana>=0.30.0
pyarrow>=12.0.0
```

---

## Project Structure (Example but keep it organized for human navigation and archive things and reduce clutter always) 

```
whale-hunter/
├── CLAUDE.md
├── requirements.txt
├── config/
│   ├── __init__.py
│   └── settings.py              # API keys, thresholds
├── src/
│   ├── __init__.py
│   ├── data/
│   │   ├── __init__.py
│   │   ├── bigquery_client.py   # EVM data fetching
│   │   ├── helius_client.py     # Solana data fetching
│   │   └── storage.py           # DuckDB operations
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── early_buyer.py       # First-N buyer detection
│   │   ├── win_rate.py          # Profitability analysis
│   │   ├── timing.py            # Entry/exit timing patterns
│   │   └── clustering.py        # Wallet network analysis
│   ├── detection/
│   │   ├── __init__.py
│   │   ├── patterns.py          # Suspicious pattern flags
│   │   ├── funding_trace.py     # Trace wallet funding sources
│   │   └── scorer.py            # Aggregate whale score
│   ├── alerts/
│   │   ├── __init__.py
│   │   └── telegram.py          # Alert notifications
│   └── utils/
│       ├── __init__.py
│       └── helpers.py
├── queries/
│   ├── ethereum/
│   │   ├── first_buyers.sql
│   │   ├── token_performance.sql
│   │   └── wallet_history.sql
│   └── solana/
│       └── helius_queries.py
├── data/
│   ├── exports/                 # BigQuery CSV exports
│   ├── whales.db               # DuckDB database
│   └── watchlist.parquet       # Confirmed whale list
├── notebooks/
│   └── exploration.ipynb       # Ad-hoc analysis
├── scripts/
│   ├── 01_fetch_historical.py
│   ├── 02_analyze_wallets.py
│   ├── 03_build_graph.py
│   └── 04_start_monitoring.py
└── tests/
    └── ...
```

---

## Core Detection Algorithms

### 1. First-N Buyer Detection (Example)

Find wallets that consistently appear in the first N buyers of tokens that later pumped.

```python
# queries/ethereum/first_buyers.sql
"""
WITH token_first_buyers AS (
    SELECT 
        to_address AS wallet,
        token_address,
        block_timestamp,
        ROW_NUMBER() OVER (
            PARTITION BY token_address 
            ORDER BY block_timestamp, transaction_index
        ) AS buy_rank
    FROM `bigquery-public-data.crypto_ethereum.token_transfers`
    WHERE block_timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 180 DAY)
),

successful_tokens AS (
    -- Tokens that did at least 10x from first trade
    -- This requires joining with DEX price data
    SELECT DISTINCT token_address
    FROM token_performance
    WHERE max_price / initial_price >= 10
)

SELECT 
    fb.wallet,
    COUNT(DISTINCT fb.token_address) AS early_hit_count,
    ARRAY_AGG(fb.token_address) AS tokens
FROM token_first_buyers fb
INNER JOIN successful_tokens st ON fb.token_address = st.token_address
WHERE fb.buy_rank <= 50  -- First 50 buyers
GROUP BY fb.wallet
HAVING early_hit_count >= 5  -- Hit on 5+ tokens
ORDER BY early_hit_count DESC
LIMIT 10000
"""
```

### 2. Wallet Clustering (Fund Flow Analysis) (Example)

```python
# src/analysis/clustering.py

import networkx as nx
from collections import defaultdict

def build_wallet_graph(transactions: pd.DataFrame) -> nx.Graph:
    """
    Build a graph of wallet relationships based on:
    1. Direct transfers between wallets
    2. Common funding sources
    3. Correlated trading behavior (same tokens, similar timing)
    
    Args:
        transactions: DataFrame with [from_address, to_address, value, timestamp, token]
    
    Returns:
        networkx Graph with wallets as nodes, relationships as edges
    """
    G = nx.Graph()
    
    # Add edges for direct transfers
    for _, tx in transactions.iterrows():
        if tx['value'] > 0:  # Only meaningful transfers
            G.add_edge(
                tx['from_address'], 
                tx['to_address'],
                type='transfer',
                value=tx['value'],
                timestamp=tx['timestamp']
            )
    
    return G


def find_wallet_clusters(G: nx.Graph, min_cluster_size: int = 3) -> list:
    """
    Identify clusters of connected wallets.
    
    Returns:
        List of wallet clusters (sets of addresses)
    """
    clusters = list(nx.connected_components(G))
    return [c for c in clusters if len(c) >= min_cluster_size]


def trace_funding_source(wallet: str, transfers: pd.DataFrame, max_depth: int = 5) -> list:
    """
    Trace the original funding source of a wallet.
    
    Returns:
        List of funding path: [source_wallet, ..., target_wallet]
    """
    path = [wallet]
    current = wallet
    
    for _ in range(max_depth):
        # Find incoming transfers to current wallet
        incoming = transfers[transfers['to_address'] == current]
        
        if incoming.empty:
            break
            
        # Get the first significant funder
        funder = incoming.sort_values('timestamp').iloc[0]['from_address']
        path.insert(0, funder)
        current = funder
    
    return path
```

### 3. Suspicious Pattern Detection (Examples)

```python
# src/detection/patterns.py

from dataclasses import dataclass
from typing import List

@dataclass
class SuspiciousPattern:
    name: str
    severity: int  # 1-5
    description: str

def detect_patterns(wallet_data: dict) -> List[SuspiciousPattern]:
    """
    Detect suspicious patterns that indicate insider knowledge.
    
    Args:
        wallet_data: Dict containing wallet metrics and history
    
    Returns:
        List of detected suspicious patterns
    """
    patterns = []
    
    # Pattern 1: Abnormally high win rate
    if wallet_data['win_rate'] > 0.70 and wallet_data['total_trades'] >= 20:
        patterns.append(SuspiciousPattern(
            name="HIGH_WIN_RATE",
            severity=5,
            description=f"Win rate {wallet_data['win_rate']:.1%} over {wallet_data['total_trades']} trades"
        ))
    
    # Pattern 2: Consistent early buyer
    if wallet_data['avg_buy_rank'] <= 20 and wallet_data['early_hits'] >= 5:
        patterns.append(SuspiciousPattern(
            name="CONSISTENT_EARLY_BUYER",
            severity=5,
            description=f"Average buy rank {wallet_data['avg_buy_rank']:.0f}, early on {wallet_data['early_hits']} pumped tokens"
        ))
    
    # Pattern 3: Same-block liquidity snipe
    if wallet_data['same_block_buys'] >= 3:
        patterns.append(SuspiciousPattern(
            name="LIQUIDITY_SNIPER",
            severity=5,
            description=f"Bought in same block as liquidity add {wallet_data['same_block_buys']} times"
        ))
    
    # Pattern 4: Precise exit timing
    if wallet_data['avg_exit_from_top_pct'] <= 0.15:  # Sells within 15% of top
        patterns.append(SuspiciousPattern(
            name="PRECISE_EXIT",
            severity=4,
            description=f"Average exit within {wallet_data['avg_exit_from_top_pct']:.1%} of local top"
        ))
    
    # Pattern 5: Fresh wallet with immediate alpha
    if wallet_data['wallet_age_days'] <= 7 and wallet_data['first_trade_profitable']:
        patterns.append(SuspiciousPattern(
            name="FRESH_WALLET_ALPHA",
            severity=4,
            description="New wallet immediately traded profitably"
        ))
    
    # Pattern 6: Part of known cluster
    if wallet_data.get('cluster_size', 1) >= 5:
        patterns.append(SuspiciousPattern(
            name="WALLET_CLUSTER",
            severity=4,
            description=f"Part of {wallet_data['cluster_size']}-wallet cluster with common funding"
        ))
    
    return patterns
```


## Data Storage Schema (DuckDB) (Example)

```python
# src/data/storage.py

import duckdb

SCHEMA = """
-- Wallet profiles
CREATE TABLE IF NOT EXISTS wallets (
    address VARCHAR PRIMARY KEY,
    chain VARCHAR,  -- 'ethereum', 'solana', 'base'
    first_seen TIMESTAMP,
    last_seen TIMESTAMP,
    total_trades INTEGER,
    win_rate FLOAT,
    whale_score FLOAT,
    cluster_id INTEGER,
    tags VARCHAR[],  -- ['sniper', 'high_win_rate', 'fresh_wallet']
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Individual trades
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY,
    wallet VARCHAR,
    chain VARCHAR,
    token_address VARCHAR,
    token_symbol VARCHAR,
    action VARCHAR,  -- 'buy', 'sell'
    amount FLOAT,
    price_usd FLOAT,
    timestamp TIMESTAMP,
    block_number BIGINT,
    tx_hash VARCHAR,
    buy_rank INTEGER,  -- Position in first buyers (NULL if not tracked)
    FOREIGN KEY (wallet) REFERENCES wallets(address)
);

-- Token launches we're tracking
CREATE TABLE IF NOT EXISTS tokens (
    address VARCHAR PRIMARY KEY,
    chain VARCHAR,
    symbol VARCHAR,
    name VARCHAR,
    launch_timestamp TIMESTAMP,
    launch_block BIGINT,
    initial_liquidity_usd FLOAT,
    peak_mcap_usd FLOAT,
    current_mcap_usd FLOAT,
    max_return_multiple FLOAT,  -- peak / initial price
    is_rugged BOOLEAN,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Wallet clusters
CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY,
    wallets VARCHAR[],
    common_funding_source VARCHAR,
    total_wallets INTEGER,
    combined_volume_usd FLOAT,
    avg_win_rate FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Detected patterns
CREATE TABLE IF NOT EXISTS patterns (
    id INTEGER PRIMARY KEY,
    wallet VARCHAR,
    pattern_name VARCHAR,
    severity INTEGER,
    description VARCHAR,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (wallet) REFERENCES wallets(address)
);

-- Whale watchlist (confirmed whales to monitor)
CREATE TABLE IF NOT EXISTS watchlist (
    wallet VARCHAR PRIMARY KEY,
    chain VARCHAR,
    whale_score FLOAT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes VARCHAR,
    alert_enabled BOOLEAN DEFAULT TRUE
);
"""

def init_database(db_path: str = "data/whales.db"):
    """Initialize DuckDB with schema."""
    con = duckdb.connect(db_path)
    con.execute(SCHEMA)
    return con
```

---

## API Clients (Example)

### BigQuery Client

```python
# src/data/bigquery_client.py

from google.cloud import bigquery
import pandas as pd

class BigQueryClient:
    def __init__(self, project_id: str = None):
        self.client = bigquery.Client(project=project_id)
    
    def query(self, sql: str) -> pd.DataFrame:
        """Execute query and return DataFrame."""
        return self.client.query(sql).to_dataframe()
    
    def get_first_buyers(self, days_back: int = 180, min_return: float = 10.0, first_n: int = 50):
        """Get wallets that were early buyers on successful tokens."""
        sql = f"""
        -- Your first buyers query here
        """
        return self.query(sql)
    
    def export_to_csv(self, sql: str, output_path: str):
        """Export query results to CSV."""
        df = self.query(sql)
        df.to_csv(output_path, index=False)
        return output_path
```

### Helius Client for Solana  (Example)

```python
# src/data/helius_client.py

import httpx
from typing import Optional, List
import asyncio

class HeliusClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = f"https://mainnet.helius-rpc.com/?api-key={api_key}"
        self.das_url = f"https://api.helius.xyz/v0"
    
    async def get_parsed_transactions(self, wallet: str, limit: int = 100) -> List[dict]:
        """Get parsed transaction history for a wallet."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.das_url}/addresses/{wallet}/transactions",
                params={"api-key": self.api_key, "limit": limit}
            )
            return response.json()
    
    async def get_token_holders(self, mint: str, limit: int = 100) -> List[dict]:
        """Get token holders sorted by balance."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTokenLargestAccounts",
                    "params": [mint]
                }
            )
            return response.json()['result']['value']
    
    async def get_signatures_for_address(self, address: str, limit: int = 1000) -> List[dict]:
        """Get transaction signatures for an address."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getSignaturesForAddress",
                    "params": [address, {"limit": limit}]
                }
            )
            return response.json()['result']
```

---

## Configuration (Example)

```python
# config/settings.py

import os
from dataclasses import dataclass

@dataclass
class Config:
    # API Keys (load from environment)
    HELIUS_API_KEY: str = os.getenv("HELIUS_API_KEY", "")
    BIGQUERY_PROJECT: str = os.getenv("BIGQUERY_PROJECT", "")
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    
    # Detection Thresholds
    MIN_WIN_RATE_THRESHOLD: float = 0.60
    MIN_EARLY_HITS: int = 5
    FIRST_N_BUYERS: int = 50
    MIN_TOKEN_RETURN_MULTIPLE: float = 10.0
    LOOKBACK_DAYS: int = 180
    
    # Whale Score Thresholds
    WHALE_SCORE_WATCHLIST: float = 60.0  # Add to watchlist if score >= this
    WHALE_SCORE_ALERT: float = 80.0       # Send alert if score >= this
    
    # Rate Limits
    HELIUS_REQUESTS_PER_SECOND: int = 10
    BIGQUERY_MAX_BYTES_BILLED: int = 10 * 1024**3  # 10 GB
    
    # Storage
    DB_PATH: str = "data/whales.db"
    EXPORTS_DIR: str = "data/exports"

config = Config()
```

---

## Execution Scripts (Examples)

### Script 1: Fetch Historical Data

```python
# scripts/01_fetch_historical.py

"""
Fetch historical data from BigQuery and save locally.
Run this first to populate initial dataset.
"""

from src.data.bigquery_client import BigQueryClient
from src.data.storage import init_database
from config.settings import config
import duckdb

def main():
    print("Initializing database...")
    con = init_database(config.DB_PATH)
    
    print("Connecting to BigQuery...")
    bq = BigQueryClient(config.BIGQUERY_PROJECT)
    
    print("Fetching first buyers data...")
    first_buyers = bq.get_first_buyers(
        days_back=config.LOOKBACK_DAYS,
        min_return=config.MIN_TOKEN_RETURN_MULTIPLE,
        first_n=config.FIRST_N_BUYERS
    )
    
    print(f"Found {len(first_buyers)} wallet candidates")
    first_buyers.to_parquet(f"{config.EXPORTS_DIR}/first_buyers.parquet")
    
    # Load into DuckDB
    con.execute("""
        INSERT INTO wallets (address, chain, tags)
        SELECT DISTINCT wallet, 'ethereum', ['early_buyer_candidate']
        FROM read_parquet('data/exports/first_buyers.parquet')
        ON CONFLICT (address) DO NOTHING
    """)
    
    print("Done!")

if __name__ == "__main__":
    main()
```

### Script 2: Analyze Wallets (Example)

```python
# scripts/02_analyze_wallets.py

"""
Analyze wallet candidates and calculate whale scores.
"""

from src.data.storage import init_database
from src.analysis.win_rate import calculate_win_rate
from src.detection.patterns import detect_patterns
from src.detection.scorer import calculate_whale_score
from config.settings import config
import duckdb
import pandas as pd

def main():
    con = duckdb.connect(config.DB_PATH)
    
    # Get candidate wallets
    candidates = con.execute("""
        SELECT address FROM wallets 
        WHERE whale_score IS NULL OR updated_at < CURRENT_TIMESTAMP - INTERVAL '1 day'
    """).fetchdf()
    
    print(f"Analyzing {len(candidates)} wallets...")
    
    results = []
    for _, row in candidates.iterrows():
        wallet = row['address']
        
        # Get wallet trades
        trades = con.execute(f"""
            SELECT * FROM trades WHERE wallet = '{wallet}'
        """).fetchdf()
        
        if trades.empty:
            continue
        
        # Calculate metrics
        metrics = calculate_win_rate(trades)
        patterns = detect_patterns(metrics)
        score = calculate_whale_score(metrics, patterns)
        
        results.append({
            'wallet': wallet,
            'whale_score': score,
            'win_rate': metrics['win_rate'],
            'total_trades': metrics['total_trades'],
            'patterns': [p.name for p in patterns]
        })
    
    # Update database
    results_df = pd.DataFrame(results)
    # ... update wallets table
    
    # Add high scorers to watchlist
    whales = results_df[results_df['whale_score'] >= config.WHALE_SCORE_WATCHLIST]
    print(f"Found {len(whales)} potential whales!")
    
    for _, whale in whales.iterrows():
        print(f"  {whale['wallet'][:16]}... Score: {whale['whale_score']:.0f}")

if __name__ == "__main__":
    main()
```

---

---


## Important Notes for Claude Code

1. **Always use DuckDB for local queries** - Never spin up PostgreSQL or other heavy databases
2. **Batch API calls** - Respect rate limits, use async where possible
3. **Parquet for exports** - Faster than CSV, smaller files
4. **BigQuery is the heavy lifter** - Do filtering/aggregation there, not locally
5. **Test with known whales first** - Validate detection accuracy before scaling
6. **Keep patterns modular** - Easy to add new detection heuristics
7. **Log everything** - Whale hunting requires audit trails (but the trails should be properly organized, we dont want unnecessary clutter)

---

## Environment Variables Required

```bash
# .env
HELIUS_API_KEY=your_helius_key
BIGQUERY_PROJECT=your_gcp_project
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
```

---

## Quick Start Commands (Examples)

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize database
python -c "from src.data.storage import init_database; init_database()"

# Fetch historical data
python scripts/01_fetch_historical.py

# Analyze wallets
python scripts/02_analyze_wallets.py

# Start monitoring (after setup complete)
python scripts/04_start_monitoring.py
```
