"""
Cost Estimator Script

This script estimates BigQuery costs WITHOUT executing any queries.
Run this BEFORE running 01_fetch_historical.py to know exact costs.

Usage:
    python scripts/estimate_costs.py
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.data.bigquery_client import BigQueryClient
from src.data.dexscreener_client import DEXScreenerClient
from config.settings import config
from google.cloud import bigquery


def estimate_query_cost(bq_client, query_sql, job_config, query_name):
    """Estimate cost for a single query."""
    try:
        # Add dry_run flag
        dry_run_config = bigquery.QueryJobConfig(
            query_parameters=job_config.query_parameters,
            dry_run=True,
            use_query_cache=False
        )

        query_job = bq_client.client.query(query_sql, job_config=dry_run_config)
        bytes_scanned = query_job.total_bytes_processed
        gb_scanned = bytes_scanned / (1024**3)
        cost_usd = (bytes_scanned / (1024**4)) * config.BIGQUERY_COST_PER_TB

        return {
            'name': query_name,
            'bytes': bytes_scanned,
            'gb': gb_scanned,
            'cost': cost_usd
        }
    except Exception as e:
        print(f"ERROR: Error estimating {query_name}: {e}")
        return None


def main():
    print("=" * 70)
    print("WHALE HUNTER - BIGQUERY COST ESTIMATOR")
    print("=" * 70)
    print()
    print("This script will estimate costs WITHOUT executing any queries.")
    print()

    # Validate configuration
    is_valid, errors = config.validate()
    if not is_valid:
        print("ERROR: Configuration errors:")
        for error in errors:
            print(f"   - {error}")
        return

    # Connect to BigQuery
    print("Step 1: Connecting to BigQuery...")
    try:
        bq = BigQueryClient(config.BIGQUERY_PROJECT)
        print("SUCCESS: Connected")
    except Exception as e:
        print(f"ERROR: Failed to connect: {e}")
        return
    print()

    # Get sample token list from DEXScreener
    print("Step 2: Getting sample token list from DEXScreener...")
    print("Note: This is FREE and helps estimate query costs")
    print()

    dex_client = DEXScreenerClient()

    try:
        # Get a small sample to estimate costs
        sample_tokens_df = dex_client.find_10x_tokens(chain="ethereum", min_return_multiple=10.0)

        if sample_tokens_df.empty:
            print("WARNING:  No 10x tokens found right now from DEXScreener")
            print("Using a test address for cost estimation...")
            # Use a known token address for estimation
            token_addresses = ["0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"]  # WETH
        else:
            token_addresses = sample_tokens_df["token_address"].tolist()
            print(f"OK: Found {len(token_addresses)} tokens for estimation")
    except Exception as e:
        print(f"WARNING:  DEXScreener error: {e}")
        print("Using test address for cost estimation...")
        token_addresses = ["0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"]

    print()

    # Estimate each query
    print("Step 3: Estimating BigQuery costs...")
    print("=" * 70)
    print()

    total_cost = 0.0
    estimates = []

    # 1. Token Launches Query
    print("1. Estimating token_launches.sql...")
    token_launches_sql_path = Path(config.QUERIES_DIR) / "token_launches.sql"
    if token_launches_sql_path.exists():
        token_launches_sql = bq.load_query_from_file(token_launches_sql_path)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("successful_token_addresses", "STRING", token_addresses),
                bigquery.ScalarQueryParameter("lookback_days", "INT64", config.LOOKBACK_DAYS)
            ]
        )

        estimate = estimate_query_cost(bq, token_launches_sql, job_config, "token_launches.sql")
        if estimate:
            estimates.append(estimate)
            total_cost += estimate['cost']
            print(f"   Will scan: {estimate['gb']:.2f} GB")
            print(f"   Cost: ${estimate['cost']:.4f}")
    else:
        print("   WARNING:  Query file not found")
    print()

    # 2. First Buyers Query (needs launch data, so we'll use empty struct for estimation)
    print("2. Estimating first_buyers.sql...")
    first_buyers_sql_path = Path(config.QUERIES_DIR) / "first_buyers.sql"
    if first_buyers_sql_path.exists():
        first_buyers_sql = bq.load_query_from_file(first_buyers_sql_path)

        # Create dummy launch data for estimation
        token_launch_data = [
            {'token_address': addr, 'launch_timestamp': '2024-01-01 00:00:00', 'launch_block': 0}
            for addr in token_addresses[:min(10, len(token_addresses))]
        ]

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("successful_token_addresses", "STRING", token_addresses),
                bigquery.ArrayQueryParameter("token_launch_data", "STRUCT", token_launch_data),
                bigquery.ScalarQueryParameter("lookback_days", "INT64", config.LOOKBACK_DAYS),
                bigquery.ScalarQueryParameter("min_early_hits", "INT64", config.MIN_EARLY_HITS)
            ]
        )

        estimate = estimate_query_cost(bq, first_buyers_sql, job_config, "first_buyers.sql")
        if estimate:
            estimates.append(estimate)
            total_cost += estimate['cost']
            print(f"   Will scan: {estimate['gb']:.2f} GB")
            print(f"   Cost: ${estimate['cost']:.4f}")
    else:
        print("   WARNING:  Query file not found")
    print()

    # 3. Wallet History Query (per-wallet cost estimation)
    print("3. Estimating wallet_history.sql...")
    wallet_history_sql_path = Path(config.QUERIES_DIR) / "wallet_history.sql"
    if wallet_history_sql_path.exists():
        wallet_history_sql = bq.load_query_from_file(wallet_history_sql_path)

        # Use sample wallets (we'll scale this)
        sample_wallets = ["0x0000000000000000000000000000000000000000"]  # Dummy for estimation
        token_launch_data = [
            {'token_address': addr, 'launch_timestamp': '2024-01-01 00:00:00', 'launch_block': 0}
            for addr in token_addresses[:min(10, len(token_addresses))]
        ]

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("wallet_addresses", "STRING", sample_wallets),
                bigquery.ArrayQueryParameter("token_launch_data", "STRUCT", token_launch_data),
                bigquery.ScalarQueryParameter("lookback_days", "INT64", config.LOOKBACK_DAYS),
                bigquery.ScalarQueryParameter("min_whale_buy_eth", "FLOAT64", config.MIN_WHALE_BUY_ETH)
            ]
        )

        estimate = estimate_query_cost(bq, wallet_history_sql, job_config, "wallet_history.sql (per wallet)")
        if estimate:
            # This is per-wallet cost, actual cost depends on candidate count
            estimates.append(estimate)
            print(f"   Will scan: {estimate['gb']:.2f} GB per wallet sample")
            print(f"   Cost: ${estimate['cost']:.4f} (this will scale with # of candidates)")
            print(f"   Note: Actual cost depends on how many whale candidates are found")
            # Conservative estimate: assume 100 candidates
            estimated_total = estimate['cost'] * 10  # Rough scaling
            total_cost += estimated_total
            print(f"   Estimated total (assuming 100 candidates): ${estimated_total:.4f}")
    else:
        print("   WARNING:  Query file not found")
    print()

    # 4. Wallet Activity Query
    print("4. Estimating wallet_activity.sql...")
    wallet_activity_sql_path = Path(config.QUERIES_DIR) / "wallet_activity.sql"
    if wallet_activity_sql_path.exists():
        wallet_activity_sql = bq.load_query_from_file(wallet_activity_sql_path)

        sample_wallets = ["0x0000000000000000000000000000000000000000"]

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("candidate_wallet_addresses", "STRING", sample_wallets),
                bigquery.ScalarQueryParameter("lookback_days", "INT64", config.LOOKBACK_DAYS)
            ]
        )

        estimate = estimate_query_cost(bq, wallet_activity_sql, job_config, "wallet_activity.sql (per wallet)")
        if estimate:
            estimates.append(estimate)
            print(f"   Will scan: {estimate['gb']:.2f} GB per wallet sample")
            print(f"   Cost: ${estimate['cost']:.4f} (this will scale with # of candidates)")
            # Conservative estimate
            estimated_total = estimate['cost'] * 10
            total_cost += estimated_total
            print(f"   Estimated total (assuming 100 candidates): ${estimated_total:.4f}")
    else:
        print("   WARNING:  Query file not found")
    print()

    # 5. Wallet Sells Query
    print("5. Estimating wallet_sells.sql...")
    wallet_sells_sql_path = Path(config.QUERIES_DIR) / "wallet_sells.sql"
    if wallet_sells_sql_path.exists():
        wallet_sells_sql = bq.load_query_from_file(wallet_sells_sql_path)

        sample_wallets = ["0x0000000000000000000000000000000000000000"]

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("candidate_wallet_addresses", "STRING", sample_wallets),
                bigquery.ArrayQueryParameter("successful_token_addresses", "STRING", token_addresses),
                bigquery.ScalarQueryParameter("lookback_days", "INT64", config.LOOKBACK_DAYS)
            ]
        )

        estimate = estimate_query_cost(bq, wallet_sells_sql, job_config, "wallet_sells.sql (per wallet)")
        if estimate:
            estimates.append(estimate)
            print(f"   Will scan: {estimate['gb']:.2f} GB per wallet sample")
            print(f"   Cost: ${estimate['cost']:.4f} (this will scale with # of candidates)")
            # Conservative estimate
            estimated_total = estimate['cost'] * 10
            total_cost += estimated_total
            print(f"   Estimated total (assuming 100 candidates): ${estimated_total:.4f}")
    else:
        print("   WARNING:  Query file not found")
    print()

    # Summary
    print("=" * 70)
    print("COST SUMMARY")
    print("=" * 70)
    print()

    for est in estimates:
        if 'per wallet' in est['name']:
            print(f"{est['name']:40} ${est['cost']:.4f} (base)")
        else:
            print(f"{est['name']:40} ${est['cost']:.4f}")

    print("-" * 70)
    print(f"{'ESTIMATED TOTAL COST':40} ${total_cost:.4f}")
    print()
    print("Notes:")
    print("- Token launches and first_buyers costs are EXACT")
    print("- Wallet-specific query costs scale with # of whale candidates found")
    print("- Estimates assume ~100 whale candidates (actual may vary)")
    print("- Whale buy filter (>= 0.1 ETH) reduces wallet_history cost")
    print()
    print("=" * 70)
    print()

    if total_cost < 0.50:
        print("OK: Total cost is very reasonable (< $0.50)")
    elif total_cost < 2.00:
        print("OK: Total cost is acceptable (< $2.00)")
    else:
        print("WARNING:  Total cost is higher than expected")
        print("   Consider reducing LOOKBACK_DAYS or FIRST_N_BUYERS in config")

    print()
    print("Ready to proceed? Run:")
    print("    python scripts/01_fetch_historical.py")
    print()


if __name__ == "__main__":
    main()
