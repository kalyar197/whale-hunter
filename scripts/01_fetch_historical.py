"""
Historical Data Fetcher Script

This script fetches historical blockchain data from BigQuery to identify
whale wallet candidates.

Usage:
    python scripts/01_fetch_historical.py

Steps:
1. Initialize DuckDB database
2. Connect to BigQuery
3. ESTIMATE costs for each query before executing
4. Fetch token performance data (successful tokens)
5. Fetch first buyers data (whale candidates)
6. Fetch wallet history for candidates
7. Export results to Parquet files
8. Load into DuckDB
9. Print summary statistics
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.data.bigquery_client import BigQueryClient
from src.data.storage import init_database, insert_wallet, insert_trades_bulk, get_database_stats
from config.settings import config
import pandas as pd


def main():
    print("=" * 70)
    print("WHALE HUNTER - HISTORICAL DATA FETCHER")
    print("=" * 70)
    print()

    # Validate configuration
    is_valid, errors = config.validate()
    if not is_valid:
        print("❌ Configuration errors:")
        for error in errors:
            print(f"   - {error}")
        print("\nPlease set up your .env file with BigQuery credentials.")
        print("See .env.example for reference.")
        return

    # Step 1: Initialize database
    print("Step 1: Initializing DuckDB database...")
    con = init_database(config.DB_PATH)
    print()

    # Step 2: Connect to BigQuery
    print("Step 2: Connecting to BigQuery...")
    try:
        bq = BigQueryClient(config.BIGQUERY_PROJECT)
    except Exception as e:
        print(f"❌ Failed to connect to BigQuery: {e}")
        return
    print()

    # Step 3: Load and estimate first_buyers query
    print("Step 3: Analyzing first_buyers query...")
    print()

    first_buyers_sql_path = Path(config.QUERIES_DIR) / "first_buyers.sql"
    if not first_buyers_sql_path.exists():
        print(f"❌ Query file not found: {first_buyers_sql_path}")
        return

    first_buyers_sql = bq.load_query_from_file(first_buyers_sql_path)

    # Estimate cost and preview row count
    analysis = bq.estimate_and_preview(first_buyers_sql)
    print()

    # Ask user to proceed
    if analysis["cost_usd"] > 0.10:  # More than 10 cents
        response = input(
            f"This query will cost ${analysis['cost_usd']:.4f}. Proceed? (y/n): "
        )
        if response.lower() != "y":
            print("Aborted by user.")
            return

    # Step 4: Execute first_buyers query
    print("\nStep 4: Executing first_buyers query...")
    try:
        first_buyers_df = bq.query(first_buyers_sql, show_estimate=False)

        # Save to parquet
        output_path = Path(config.EXPORTS_DIR) / "first_buyers.parquet"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        first_buyers_df.to_parquet(output_path, index=False)
        print(f"✓ Saved to {output_path}")
    except Exception as e:
        print(f"❌ Query failed: {e}")
        return
    print()

    # Step 5: Load candidate wallets into database
    print("Step 5: Loading candidate wallets into database...")
    for _, row in first_buyers_df.iterrows():
        insert_wallet(con, row["wallet"], "ethereum", tags=["early_buyer_candidate"])

    print(f"✓ Loaded {len(first_buyers_df)} candidate wallets")
    print()

    # Step 6: Fetch wallet history for candidates (if we have candidates)
    if len(first_buyers_df) > 0:
        print("Step 6: Fetching wallet trade history...")
        print(f"Note: This will fetch history for {len(first_buyers_df)} wallets")

        # Get wallet addresses
        wallet_addresses = first_buyers_df["wallet"].tolist()

        # Load wallet history query
        wallet_history_sql_path = Path(config.QUERIES_DIR) / "wallet_history.sql"
        if not wallet_history_sql_path.exists():
            print(f"⚠️  Query file not found: {wallet_history_sql_path}")
            print("   Skipping wallet history fetch.")
        else:
            wallet_history_sql = bq.load_query_from_file(wallet_history_sql_path)

            # Prepare parameterized query
            from google.cloud import bigquery

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter(
                        "wallet_addresses", "STRING", wallet_addresses
                    )
                ]
            )

            print("\nEstimating wallet_history query cost...")
            # For parameterized queries, we estimate with a subset
            sample_addresses = wallet_addresses[:min(10, len(wallet_addresses))]
            sample_job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter(
                        "wallet_addresses", "STRING", sample_addresses
                    )
                ],
                dry_run=True,
                use_query_cache=False,
            )

            try:
                query_job = bq.client.query(wallet_history_sql, job_config=sample_job_config)
                bytes_scanned = query_job.total_bytes_processed
                gb_scanned = bytes_scanned / (1024**3)
                cost_usd = (bytes_scanned / (1024**4)) * config.BIGQUERY_COST_PER_TB

                # Estimate for all wallets (rough approximation)
                scaling_factor = len(wallet_addresses) / len(sample_addresses)
                estimated_total_cost = cost_usd * scaling_factor

                print(f"Estimated cost for all {len(wallet_addresses)} wallets: ${estimated_total_cost:.4f}")

                if estimated_total_cost > 0.50:  # More than 50 cents
                    response = input(f"Proceed with wallet history fetch? (y/n): ")
                    if response.lower() != "y":
                        print("Skipped wallet history fetch.")
                    else:
                        # Execute query
                        print("Fetching wallet history...")
                        trades_df = bq.client.query(
                            wallet_history_sql, job_config=job_config
                        ).to_dataframe()

                        # Save to parquet
                        output_path = Path(config.EXPORTS_DIR) / "wallet_history.parquet"
                        trades_df.to_parquet(output_path, index=False)
                        print(f"✓ Saved {len(trades_df)} trades to {output_path}")

                        # Load into database
                        if len(trades_df) > 0:
                            insert_trades_bulk(con, trades_df)
                            print(f"✓ Loaded {len(trades_df)} trades into database")
                else:
                    # Cost is acceptable, just execute
                    print("Fetching wallet history...")
                    trades_df = bq.client.query(
                        wallet_history_sql, job_config=job_config
                    ).to_dataframe()

                    # Save and load
                    output_path = Path(config.EXPORTS_DIR) / "wallet_history.parquet"
                    trades_df.to_parquet(output_path, index=False)
                    print(f"✓ Saved {len(trades_df)} trades to {output_path}")

                    if len(trades_df) > 0:
                        insert_trades_bulk(con, trades_df)
                        print(f"✓ Loaded {len(trades_df)} trades into database")

            except Exception as e:
                print(f"⚠️  Error fetching wallet history: {e}")

    print()

    # Step 7: Print summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)

    stats = get_database_stats(con)
    print(f"Database: {config.DB_PATH}")
    print(f"Wallets: {stats['wallets']}")
    print(f"Trades: {stats['trades']}")
    print(f"Tokens: {stats['tokens']}")
    print(f"Patterns: {stats['patterns']}")
    print(f"Watchlist: {stats['watchlist']}")
    print()

    print("✓ Historical data fetch completed!")
    print("\nNext step: Run 02_analyze_wallets.py to calculate whale scores")
    print("=" * 70)

    # Close connection
    con.close()


if __name__ == "__main__":
    main()
