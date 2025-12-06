# Whale Hunter

A blockchain analytics system for detecting insider trading patterns and identifying "whale" wallets through on-chain forensics.

**Primary Target**: Ethereum/Base EVM chains (with future Solana support)
**Goal**: Find wallets that consistently buy tokens early (before pumps) with abnormally high success rates

## Features

- **Historical Analysis**: Identify whale wallets from past blockchain data
- **Pattern Detection**: Detect 5 key suspicious patterns with context-aware severity
- **Activity Density Filtering**: Eliminate spray-and-pray bots (90% false positive reduction)
- **Strategic Dumper Detection**: Distinguish predators from believers via sell tracking
- **Whale Scoring**: 0-100 scoring with precision penalty for accurate ranking
- **Cost Estimation**: BigQuery dry-run mode to preview costs before spending
- **Local Analytics**: DuckDB for fast local analysis without external dependencies

## Project Structure

```
whale-hunter/
├── config/                  # Configuration and settings
├── src/
│   ├── data/               # Data fetching and storage
│   ├── analysis/           # Analysis modules
│   ├── detection/          # Pattern detection and scoring
│   └── utils/              # Utility functions
├── queries/ethereum/        # SQL queries for BigQuery
├── scripts/                # Execution scripts
├── data/                   # Local database and exports
└── CLAUDE.md               # Detailed technical documentation
```

## Prerequisites

- Python 3.9 or higher
- Google Cloud Platform account with BigQuery access
- GCP service account with BigQuery permissions

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Up Google Cloud BigQuery

#### a. Create GCP Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Note your Project ID

#### b. Enable BigQuery API

1. In GCP Console, go to **APIs & Services** > **Library**
2. Search for "BigQuery API"
3. Click **Enable**

#### c. Create Service Account

1. Go to **IAM & Admin** > **Service Accounts**
2. Click **Create Service Account**
3. Name it (e.g., "whale-hunter")
4. Grant role: **BigQuery User** and **BigQuery Data Viewer**
5. Click **Create Key** > **JSON**
6. Download the JSON file to your computer

#### d. Note BigQuery Free Tier

- BigQuery offers 1 TB of query processing per month for free
- Queries in this project typically use 10-100 GB per run
- Dry-run estimation is always FREE and helps you avoid costs

### 3. Configure Environment Variables

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Edit `.env` and add your credentials:

```env
BIGQUERY_PROJECT=your_gcp_project_id
GOOGLE_APPLICATION_CREDENTIALS=C:\path\to\your\service-account-key.json
```

### 4. Initialize Database

The database will be automatically created when you run the first script, but you can test it:

```bash
python -c "from src.data.storage import init_database; init_database()"
```

## Quick Start

### Step 1: Fetch Historical Data

This script fetches whale candidates from BigQuery:

```bash
python scripts/01_fetch_historical.py
```

**What it does:**
- Calls DEXScreener API to identify 10x tokens (FREE)
- Connects to BigQuery
- Estimates query costs (dry run - FREE)
- Asks for confirmation before spending money
- Fetches wallets that were early buyers (rank 1-100) on successful tokens
- Fetches total wallet activity to calculate precision rate
- Fetches sell behavior to identify strategic dumpers
- Saves results to `data/whales.db` and `data/exports/`

**Expected output:**
- 100-500 candidate wallet addresses
- Trade history for each wallet
- Activity density data (total tokens traded)
- Sell behavior data (strategic exits)
- Total cost: $0.75 - $1.50 (4 BigQuery queries)

### Step 2: Analyze Wallets

This script calculates whale scores for all candidates:

```bash
python scripts/02_analyze_wallets.py
```

**What it does:**
- Loads activity density and sell behavior data
- Calculates metrics for each wallet
- Calculates precision rate (filters spray-and-pray bots)
- Detects suspicious patterns (5 patterns, context-aware)
- Assigns whale score (0-100) with precision penalty
- Generates watchlist of high-scoring wallets
- Saves detailed report to `data/whale_report.csv`

**Expected output:**
- Top 20 whale wallets with scores
- Precision rates for each wallet (signal-to-noise ratio)
- Strategic exit counts (dumpers vs holders)
- Detailed reports for top 3 whales
- Watchlist of wallets scoring >= 60

## Understanding the Results

### Whale Score (0-100)

The whale score is composed of four components:

1. **Early Hit Score (0-50 points)**: Number of successful tokens bought early
   - 10 points per early hit, capped at 50

2. **Buy Rank Score (0-30 points)**: How early they bought (weighted scoring)
   - Rank 1-25: 30 points (aggressive insider)
   - Rank 26-50: 30 → 24 points (gradual decrease)
   - Rank 51-100: 24 → 10 points (stealth insider)
   - Lower average buy rank = higher score

3. **Pattern Score (0-20 points)**: Detected suspicious patterns
   - Sum of pattern severities × 4

4. **Precision Penalty (×0.2 to ×1.0)**: CRITICAL - Filters spray-and-pray bots
   - Precision < 1% + 500+ tokens: 80% penalty (keeps 20% of score)
   - Precision < 5% + 200+ tokens: 50% penalty (keeps 50% of score)
   - Precision < 10% + 100+ tokens: 30% penalty (keeps 70% of score)
   - Final Score = Base Score × Precision Penalty

### Score Categories

- **80-100**: HIGH PRIORITY WHALE (likely insider)
- **60-79**: WATCHLIST (strong evidence)
- **40-59**: MODERATE INTEREST
- **20-39**: LOW INTEREST
- **0-19**: MINIMAL INTEREST

### Detected Patterns

1. **CONSISTENT_EARLY_BUYER** (Severity 5)
   - Avg buy rank ≤ 20, 5+ early hits

2. **LIQUIDITY_SNIPER** (Severity 2 or 5) - Context-Aware
   - Fresh wallet (< 7 days) + 3+ same-block buys = Severity 5 (INSIDER)
   - Old wallet + 3+ same-block buys = Severity 2 (MEV bot noise)

3. **FRESH_WALLET_ALPHA** (Severity 4)
   - New wallet (<7 days) immediately sniping

4. **WALLET_CLUSTER** (Severity 4)
   - Part of 5+ wallet cluster (potential Sybil attack)

5. **STRATEGIC_DUMPER** (Severity 4-5) - NEW
   - 3+ strategic exits (sold >50% of position)
   - Severity 5: Quick flipper (<48h hold time) - likely insider
   - Severity 4: Profit taker (longer hold) - trader behavior

## Cost Management

### BigQuery Costs

- **Pricing**: $5 per TB scanned
- **Free tier**: 1 TB per month
- **Typical costs**: $0.75 - $1.50 per run (4 queries)
  - first_buyers.sql: $0.25-0.50 (rank 1-100)
  - wallet_activity.sql: $0.25-0.50 (NEW - activity density)
  - wallet_sells.sql: $0.25-0.50 (NEW - sell tracking)
  - wallet_history.sql: $0.10-0.25 (trade details)

### Cost Estimation

The system ALWAYS estimates costs before executing queries:

```python
from src.data.bigquery_client import BigQueryClient

bq = BigQueryClient()

# Estimate cost (FREE - uses dry run mode)
estimate = bq.estimate_query_cost(sql)
print(f"Will scan {estimate['gb_scanned']:.2f} GB (${estimate['cost_usd']:.4f})")

# Preview row count
row_count = bq.preview_result_count(sql)
print(f"Expected results: ~{row_count:,} rows")

# Execute if acceptable
if estimate['cost_usd'] < 0.10:
    results = bq.query(sql)
```

### Optimization Tips

1. **Reduce date range**: Use 90 days instead of 180
2. **Filter tokens**: Add minimum holder count thresholds
3. **Limit results**: Use LIMIT clause in queries
4. **Use partitioned tables**: BigQuery public datasets are partitioned by date

## Configuration

Edit `config/settings.py` to adjust thresholds:

```python
# Detection Thresholds
MIN_EARLY_HITS = 5              # Min early hits to be considered
FIRST_N_BUYERS = 100            # Consider first N buyers as "early" (EXPANDED from 50)
MIN_TOKEN_RETURN_MULTIPLE = 10.0  # Token must achieve 10x

# Pattern Detection
LIQUIDITY_SNIPER_MIN_HITS = 3   # Min same-block buys
FRESH_WALLET_DAYS = 7           # New wallet threshold
STRATEGIC_DUMPER_MIN_EXITS = 3  # Min strategic exits (NEW)
```

## Data Files

After running the scripts, you'll have:

- `data/whales.db`: DuckDB database with all data
- `data/exports/successful_tokens.csv`: 10x tokens from DEXScreener
- `data/exports/first_buyers.parquet`: Candidate wallets (rank 1-100)
- `data/exports/wallet_history.parquet`: Trade history
- `data/exports/wallet_activity.parquet`: Total activity for precision calculation (NEW)
- `data/exports/wallet_sells.parquet`: Sell behavior data (NEW)
- `data/whale_report.csv`: Analysis results with precision rates

## Advanced Usage

### Query Specific Wallets

```python
from src.data.storage import get_wallet_trades
import duckdb

con = duckdb.connect('data/whales.db')
trades = get_wallet_trades(con, '0x1234...')
print(trades)
```

### Custom Analysis

```python
from src.analysis.early_buyer import analyze_early_buying_pattern
from src.detection.patterns import detect_patterns
from src.detection.scorer import calculate_whale_score

# Analyze a wallet
metrics = analyze_early_buying_pattern(trades_df)
patterns = detect_patterns(metrics)
score = calculate_whale_score(metrics, patterns)
```

## Troubleshooting

### "BIGQUERY_PROJECT not set"

Make sure your `.env` file exists and has the correct values. Copy from `.env.example`.

### "Service account file not found"

Check that the path in `GOOGLE_APPLICATION_CREDENTIALS` is correct and the file exists.

### "Query failed: 403 Forbidden"

Your service account needs **BigQuery User** and **BigQuery Data Viewer** roles.

### "No wallets found"

The queries might be too restrictive. Try:
- Reducing `MIN_EARLY_HITS` in `config/settings.py`
- Increasing date range
- Checking if BigQuery public datasets are accessible

## Future Enhancements

- Solana integration (Helius API)
- Real-time monitoring with Telegram alerts
- Web dashboard for visualization
- Graph analysis for wallet clustering
- Integration with DEX APIs for real-time prices

## Security & Privacy

- This tool analyzes PUBLIC blockchain data only
- No private keys or wallet access required
- All data is read-only from public sources

## License

MIT License - See CLAUDE.md for detailed technical documentation

## Support

For issues or questions:
1. Check CLAUDE.md for detailed technical docs
2. Review example outputs in `data/` directory
3. Verify BigQuery setup and credentials
4. Check query costs with dry-run mode

## Acknowledgments

- Data source: BigQuery Public Datasets (crypto_ethereum)
- Built with: DuckDB, pandas, networkx, google-cloud-bigquery
