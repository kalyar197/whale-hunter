# Whale Hunter

A blockchain analytics system for detecting insider trading patterns and identifying "whale" wallets through on-chain forensics.

**Primary Target**: Ethereum/Base EVM chains (with future Solana support)
**Goal**: Find wallets that consistently buy tokens early (before pumps) with abnormally high success rates

## Features

- **Historical Analysis**: Identify whale wallets from past blockchain data
- **Pattern Detection**: Detect 5 key suspicious patterns (early buying, sniping, clustering, etc.)
- **Whale Scoring**: 0-100 scoring system to rank wallet suspiciousness
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
- Connects to BigQuery
- Estimates query costs (dry run - FREE)
- Asks for confirmation before spending money
- Fetches wallets that were early buyers on successful tokens
- Saves results to `data/whales.db` and `data/exports/`

**Expected output:**
- 100-500 candidate wallet addresses
- Trade history for each wallet
- Total cost: $0.10 - $0.50 (depending on filters)

### Step 2: Analyze Wallets

This script calculates whale scores for all candidates:

```bash
python scripts/02_analyze_wallets.py
```

**What it does:**
- Calculates metrics for each wallet
- Detects suspicious patterns
- Assigns whale score (0-100)
- Generates watchlist of high-scoring wallets
- Saves detailed report to `data/whale_report.csv`

**Expected output:**
- Top 20 whale wallets with scores
- Detailed reports for top 3 whales
- Watchlist of wallets scoring >= 60

## Understanding the Results

### Whale Score (0-100)

The whale score is composed of three components:

1. **Early Hit Score (0-50 points)**: Number of successful tokens bought early
   - 10 points per early hit, capped at 50

2. **Buy Rank Score (0-30 points)**: How early they bought
   - Lower average buy rank = higher score
   - Rank 1 = 30 points, Rank 50 = 0 points

3. **Pattern Score (0-20 points)**: Detected suspicious patterns
   - Sum of pattern severities × 4

### Score Categories

- **80-100**: HIGH PRIORITY WHALE (likely insider)
- **60-79**: WATCHLIST (strong evidence)
- **40-59**: MODERATE INTEREST
- **20-39**: LOW INTEREST
- **0-19**: MINIMAL INTEREST

### Detected Patterns

1. **CONSISTENT_EARLY_BUYER** (Severity 5)
   - Avg buy rank ≤ 20, 5+ early hits

2. **LIQUIDITY_SNIPER** (Severity 5)
   - 3+ same-block buys (bought in same block as liquidity add)

3. **HIGH_VOLUME_EARLY** (Severity 4)
   - Large buys (>1 ETH) in first 50 buyers, 5+ times

4. **FRESH_WALLET_ALPHA** (Severity 4)
   - New wallet (<7 days) immediately sniping

5. **WALLET_CLUSTER** (Severity 4)
   - Part of 5+ wallet cluster (potential Sybil attack)

## Cost Management

### BigQuery Costs

- **Pricing**: $5 per TB scanned
- **Free tier**: 1 TB per month
- **Typical costs**: $0.10 - $0.50 per run

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
FIRST_N_BUYERS = 50             # Consider first N buyers as "early"
MIN_TOKEN_RETURN_MULTIPLE = 10.0  # Token must achieve 10x

# Pattern Detection
LIQUIDITY_SNIPER_MIN_HITS = 3   # Min same-block buys
HIGH_VOLUME_THRESHOLD_ETH = 1.0  # Large buy threshold
FRESH_WALLET_DAYS = 7           # New wallet threshold
```

## Data Files

After running the scripts, you'll have:

- `data/whales.db`: DuckDB database with all data
- `data/exports/first_buyers.parquet`: Candidate wallets
- `data/exports/wallet_history.parquet`: Trade history
- `data/whale_report.csv`: Analysis results

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
