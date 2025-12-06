# Whale Hunter - Complete Workflow

## The Critical Problem (SOLVED)

**Problem**: BigQuery alone cannot identify 10x tokens
- Transfer count ≠ profitability
- Rugpulls can have high activity too
- Need actual price data to find successful tokens

**Solution**: DEXScreener API → BigQuery
1. DEXScreener identifies 10x tokens (FREE API)
2. Pass token list to BigQuery
3. BigQuery finds early buyers on those specific tokens

---

## Updated Pipeline

### Phase 1: Identify Successful Tokens

**Tool**: DEXScreener API (FREE, no auth required)

```python
from src.data.dexscreener_client import DEXScreenerClient

client = DEXScreenerClient()

# Get tokens that did 10x+ (based on 24h price changes as proxy)
successful_tokens = client.find_10x_tokens(
    chain="ethereum",
    min_return_multiple=10.0
)

# Returns: token_address, symbol, price_change_24h, liquidity, etc.
```

**Output**: List of token addresses that pumped

**Limitations**:
- Uses 24h price change as proxy (not perfect)
- Tokens with >500% 24h gain likely did 10x over longer period
- For more accurate data, consider:
  - Dune Analytics (pre-indexed DEX data)
  - Manual verification
  - Historical price APIs

---

### Phase 2: Find Early Buyers on Those Tokens

**Tool**: BigQuery + Modified first_buyers.sql

```python
from google.cloud import bigquery

# Get successful token addresses from Phase 1
token_addresses = successful_tokens["token_address"].tolist()

# Pass to BigQuery as parameter
job_config = bigquery.QueryJobConfig(
    query_parameters=[
        bigquery.ArrayQueryParameter(
            "successful_token_addresses",
            "STRING",
            token_addresses
        )
    ]
)

# Execute query
results = bq.client.query(first_buyers_sql, job_config=job_config)
```

**What it does**:
- Searches ONLY the successful tokens
- Finds wallets in first 50 buyers
- Counts early hits per wallet
- Returns wallets with 5+ early hits

**Output**: Whale candidate addresses

---

### Phase 3: Analyze Wallet Patterns

**Tool**: 02_analyze_wallets.py

```bash
python scripts/02_analyze_wallets.py
```

**What it does**:
- Calculates metrics for each candidate
- Detects 5 suspicious patterns
- Assigns whale score (0-100)
- Adds high scorers to watchlist

**Output**: Ranked whale list with scores

---

## Complete Command Sequence

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up environment
cp .env.example .env
# Edit .env with BigQuery credentials

# 3. Run pipeline
python scripts/01_fetch_historical.py
# This now:
#   - Calls DEXScreener API (Step 3)
#   - Gets 10x tokens
#   - Passes to BigQuery (Step 4-5)
#   - Finds early buyers
#   - Saves results

# 4. Analyze candidates
python scripts/02_analyze_wallets.py
```

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│ PHASE 1: IDENTIFY SUCCESSFUL TOKENS                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   DEXScreener API (FREE)                                    │
│   ↓                                                         │
│   Find tokens with >500% 24h gains                          │
│   ↓                                                         │
│   Filter by liquidity (>$50K) & volume (>$10K)              │
│   ↓                                                         │
│   Export: successful_tokens.csv                             │
│   (~20-100 token addresses)                                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ PHASE 2: FIND EARLY BUYERS (BigQuery)                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   Input: Token addresses from Phase 1                       │
│   ↓                                                         │
│   Query ethereum.token_transfers                            │
│   ↓                                                         │
│   Rank buyers by timestamp                                  │
│   ↓                                                         │
│   Filter: First 50 buyers per token                         │
│   ↓                                                         │
│   Aggregate: Wallets with 5+ early hits                     │
│   ↓                                                         │
│   Export: first_buyers.parquet                              │
│   (~100-500 candidate wallets)                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ PHASE 3: ANALYZE & SCORE (Local DuckDB)                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   For each candidate wallet:                                │
│   ↓                                                         │
│   Calculate metrics (trades, volume, age)                   │
│   ↓                                                         │
│   Detect patterns (sniping, clustering, etc.)               │
│   ↓                                                         │
│   Calculate whale score (0-100)                             │
│   ↓                                                         │
│   Add to watchlist if score >= 60                           │
│   ↓                                                         │
│   Export: whale_report.csv                                  │
│   (~10-50 confirmed whales)                                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## API Endpoints Used

### DEXScreener (No Auth Required)

**Endpoint**: `https://api.dexscreener.com/latest/dex/tokens/trending/{chain}`

**Rate Limit**: ~300 requests/minute

**Returns**:
```json
{
  "pairs": [{
    "baseToken": {"address": "0x...", "symbol": "TOKEN"},
    "priceUsd": "0.001234",
    "priceChange": {"h24": 567.89},
    "liquidity": {"usd": 123456},
    "volume": {"h24": 234567}
  }]
}
```

**Free**: Yes
**Documentation**: https://docs.dexscreener.com/

---

## Alternative Data Sources

If DEXScreener doesn't meet your needs:

### 1. **Dune Analytics** (Better Data)
- Pre-indexed DEX trades with prices
- Can query actual 10x tokens with SQL
- Free tier available
- Requires API key

```sql
-- Dune query example
SELECT
    token_address,
    MAX(price_usd) / MIN(price_usd) as max_return
FROM dex.trades
WHERE block_time > NOW() - INTERVAL '180 days'
GROUP BY token_address
HAVING max_return >= 10
```

### 2. **CoinGecko API** (Historical Prices)
- Get token price history
- Free tier: 10-50 calls/minute
- More accurate historical data

### 3. **The Graph** (On-chain)
- Query Uniswap subgraphs directly
- No rate limits on public endpoint
- Most accurate but complex queries

### 4. **Manual List** (Most Accurate)
- Research successful tokens manually
- Verify returns on DEXTools/DexScreener
- Pass addresses directly to BigQuery

```python
# Manual approach
successful_tokens = [
    "0x...",  # TOKEN1 - did 50x
    "0x...",  # TOKEN2 - did 25x
    "0x...",  # TOKEN3 - did 15x
]

# Use in BigQuery query
job_config = bigquery.QueryJobConfig(
    query_parameters=[
        bigquery.ArrayQueryParameter(
            "successful_token_addresses",
            "STRING",
            successful_tokens
        )
    ]
)
```

---

## Cost Breakdown

| Component | Cost | Notes |
|-----------|------|-------|
| DEXScreener API | FREE | No auth required |
| BigQuery (1st run) | $0.10-0.50 | ~50-100 GB scanned |
| BigQuery (subsequent) | $0.05-0.20 | Smaller date ranges |
| DuckDB | FREE | Local storage |
| Total MVP | ~$0.50 | One-time setup cost |

---

## Troubleshooting

### "No successful tokens found"

**Possible causes**:
1. DEXScreener API down
2. No tokens currently pumping
3. Rate limit hit

**Solutions**:
- Try different chain (base, bsc)
- Lower min_return_multiple to 5x
- Use manual token list
- Try again in a few hours

### "BigQuery returns 0 wallets"

**Possible causes**:
1. Token list is too restrictive
2. No early buyer data in BigQuery
3. Tokens are too new

**Solutions**:
- Increase FIRST_N_BUYERS to 100
- Lower MIN_EARLY_HITS to 3
- Check token_addresses are lowercase
- Verify tokens exist in BigQuery dataset

---

## Example Output

### successful_tokens.csv
```csv
token_address,symbol,price_change_24h,liquidity_usd
0x1234...,PEPE,678.5,125000
0x5678...,WOJAK,523.2,89000
```

### first_buyers.parquet
```
wallet,early_hit_count,avg_buy_rank
0xabc...,7,12.3
0xdef...,6,8.5
```

### whale_report.csv
```
wallet,whale_score,early_hits,patterns
0xabc...,85.2,7,"CONSISTENT_EARLY_BUYER,LIQUIDITY_SNIPER"
0xdef...,72.8,6,"CONSISTENT_EARLY_BUYER"
```

---

## Next Steps

After MVP is working:
1. **Automate**: Run daily to find new whales
2. **Real-time**: Add Telegram alerts when whales buy
3. **Solana**: Add Helius API for Solana memecoins
4. **Backtesting**: Validate whale performance
5. **Copy Trading**: Auto-follow whale trades
