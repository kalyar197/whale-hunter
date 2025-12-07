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
from src.data.geckoterminal_client import GeckoTerminalClient
from src.data.storage import init_database, insert_wallet, insert_trades_bulk, get_database_stats
from config.settings import config
import pandas as pd
from google.cloud import bigquery


def main():
    print("=" * 70)
    print("WHALE HUNTER - HISTORICAL DATA FETCHER")
    print("=" * 70)
    print()

    # Validate configuration
    is_valid, errors = config.validate()
    if not is_valid:
        print("ERROR: Configuration errors:")
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
        print(f"ERROR: Failed to connect to BigQuery: {e}")
        return
    print()

    # Step 3: Check for existing tokens or fetch from GeckoTerminal
    successful_tokens_path = Path(config.EXPORTS_DIR) / "successful_tokens.csv"

    # FIRST check if we already have tokens (e.g., from Dune Analytics)
    if successful_tokens_path.exists():
        print("Step 3: Found existing successful_tokens.csv - using manual token list")
        print("Note: Skipping GeckoTerminal API (using Dune Analytics or manual tokens)")
        print()
        successful_tokens_df = pd.read_csv(successful_tokens_path)
        print(f"OK: Loaded {len(successful_tokens_df)} tokens from {successful_tokens_path}")
        print()
    else:
        # If no existing CSV, fetch from GeckoTerminal
        print("Step 3: Fetching 4x+ tokens from GeckoTerminal API...")
        print("Note: Getting ALL tokens with 4x+ gains (including pump-and-dumps)")
        print("Goal: Find insiders behind pumps!")
        print()

        gecko_client = GeckoTerminalClient()

        print("Querying GeckoTerminal for 4x+ tokens...")
        print()

        # Simple 4x detection - we WANT pump-and-dumps!
        successful_tokens_df = gecko_client.find_4x_tokens(network="eth", min_return_multiple=4.0)

        if successful_tokens_df.empty:
            print("ERROR: No 4x+ tokens found from GeckoTerminal")
            print("This might be because:")
            print("  - No tokens currently meet the 4x criteria")
            print("  - Market is slow today")
            print("  - GeckoTerminal API rate limit")
            print("\nYou can manually create data/exports/successful_tokens.csv with token addresses.")
            print("Format: token_address,symbol,name,price_change_24h,liquidity_usd,volume_24h,pair_created_at,estimated_return")
            return

        # Save successful tokens list
        successful_tokens_path.parent.mkdir(parents=True, exist_ok=True)
        successful_tokens_df.to_csv(successful_tokens_path, index=False)
        print(f"OK: Saved {len(successful_tokens_df)} 4x+ tokens to {successful_tokens_path}")
        print()

    # Get list of token addresses for BigQuery
    token_addresses = successful_tokens_df["token_address"].tolist()
    print(f"Found {len(token_addresses)} token addresses to search for early buyers")
    print()

    # Step 4: Load and estimate first_buyers query (SIMPLIFIED - no LP detection)
    print("Step 4: Finding first buyers...")
    print("Note: Ranking from first transfer (not LP creation)")
    print("Note: Other filters (precision rate, activity density) will remove garbage")
    print()

    first_buyers_sql_path = Path(config.QUERIES_DIR) / "first_buyers_simple.sql"
    if not first_buyers_sql_path.exists():
        print(f"ERROR: Query file not found: {first_buyers_sql_path}")
        return

    first_buyers_sql = bq.load_query_from_file(first_buyers_sql_path)

    # Prepare query parameters (no LP data needed)
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter(
                "successful_token_addresses",
                "STRING",
                token_addresses
            ),
            bigquery.ScalarQueryParameter(
                "lookback_days", "INT64", config.LOOKBACK_DAYS
            ),
            bigquery.ScalarQueryParameter(
                "min_early_hits", "INT64", config.MIN_EARLY_HITS
            )
        ]
    )

    # Estimate cost (with parameters)
    print("Estimating query cost...")
    dry_run_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter(
                "successful_token_addresses",
                "STRING",
                token_addresses
            ),
            bigquery.ScalarQueryParameter(
                "lookback_days", "INT64", config.LOOKBACK_DAYS
            ),
            bigquery.ScalarQueryParameter(
                "min_early_hits", "INT64", config.MIN_EARLY_HITS
            )
        ],
        dry_run=True,
        use_query_cache=False
    )

    query_job = bq.client.query(first_buyers_sql, job_config=dry_run_config)
    bytes_scanned = query_job.total_bytes_processed
    gb_scanned = bytes_scanned / (1024**3)
    cost_usd = (bytes_scanned / (1024**4)) * config.BIGQUERY_COST_PER_TB

    print(f"Query will scan {gb_scanned:.2f} GB (${cost_usd:.4f})")
    print()

    # Ask user to proceed
    if cost_usd > 0.10:  # More than 10 cents
        response = input(
            f"This query will cost ${cost_usd:.4f}. Proceed? (y/n): "
        )
        if response.lower() != "y":
            print("Aborted by user.")
            return

    # Step 5: Execute first_buyers query
    print("\nStep 5: Executing first_buyers query with actual LP creation data...")
    try:
        first_buyers_df = bq.client.query(first_buyers_sql, job_config=job_config).to_dataframe()
        print(f"OK: Query completed. Retrieved {len(first_buyers_df):,} rows")

        # Save to parquet
        output_path = Path(config.EXPORTS_DIR) / "first_buyers.parquet"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        first_buyers_df.to_parquet(output_path, index=False)
        print(f"OK: Saved to {output_path}")
    except Exception as e:
        print(f"ERROR: Query failed: {e}")
        return
    print()

    # Step 6: Load candidate wallets into database
    print("Step 6: Loading candidate wallets into database...")
    for _, row in first_buyers_df.iterrows():
        insert_wallet(con, row["wallet"], "ethereum", tags=["early_buyer_candidate"])

    print(f"OK: Loaded {len(first_buyers_df)} candidate wallets")
    print()

    # Step 7: Fetch wallet history for candidates (if we have candidates)
    if len(first_buyers_df) > 0:
        print("Step 7: Fetching wallet trade history...")
        print(f"Note: This will fetch history for {len(first_buyers_df)} wallets")

        # Get wallet addresses
        wallet_addresses = first_buyers_df["wallet"].tolist()

        # Load simplified wallet history query (no LP data needed)
        wallet_history_sql_path = Path(config.QUERIES_DIR) / "wallet_history_simple.sql"
        if not wallet_history_sql_path.exists():
            print(f"WARNING: Query file not found: {wallet_history_sql_path}")
            print("  Skipping wallet history fetch (pattern detection will be disabled).")
            wallet_history_sql_path = None

        if wallet_history_sql_path is not None:
            wallet_history_sql = bq.load_query_from_file(wallet_history_sql_path)

            # Prepare parameterized query
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter(
                        "successful_token_addresses",
                        "STRING",
                        token_addresses
                    ),
                    bigquery.ArrayQueryParameter(
                        "wallet_addresses", "STRING", wallet_addresses
                    ),
                    bigquery.ScalarQueryParameter(
                        "lookback_days", "INT64", config.LOOKBACK_DAYS
                    ),
                    bigquery.ScalarQueryParameter(
                        "min_whale_buy_eth", "FLOAT64", config.MIN_WHALE_BUY_ETH
                    )
                ]
            )

            print("\nEstimating wallet_history query cost...")
            print(f"Note: Filtering buys >= {config.MIN_WHALE_BUY_ETH} ETH to exclude small buyers")
            # For parameterized queries, we estimate with a subset
            sample_addresses = wallet_addresses[:min(10, len(wallet_addresses))]
            sample_job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter(
                        "successful_token_addresses",
                        "STRING",
                        token_addresses
                    ),
                    bigquery.ArrayQueryParameter(
                        "wallet_addresses", "STRING", sample_addresses
                    ),
                    bigquery.ScalarQueryParameter(
                        "lookback_days", "INT64", config.LOOKBACK_DAYS
                    ),
                    bigquery.ScalarQueryParameter(
                        "min_whale_buy_eth", "FLOAT64", config.MIN_WHALE_BUY_ETH
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
                        print(f"OK: Saved {len(trades_df)} trades to {output_path}")

                        # Load into database
                        if len(trades_df) > 0:
                            insert_trades_bulk(con, trades_df)
                            print(f"OK: Loaded {len(trades_df)} trades into database")
                else:
                    # Cost is acceptable, just execute
                    print("Fetching wallet history...")
                    trades_df = bq.client.query(
                        wallet_history_sql, job_config=job_config
                    ).to_dataframe()

                    # Save and load
                    output_path = Path(config.EXPORTS_DIR) / "wallet_history.parquet"
                    trades_df.to_parquet(output_path, index=False)
                    print(f"OK: Saved {len(trades_df)} trades to {output_path}")

                    if len(trades_df) > 0:
                        insert_trades_bulk(con, trades_df)
                        print(f"OK: Loaded {len(trades_df)} trades into database")

            except Exception as e:
                print(f"WARNING:  Error fetching wallet history: {e}")

    print()

    # Step 8: Fetch wallet activity density (CRITICAL for filtering spray-and-pray bots)
    if len(first_buyers_df) > 0:
        print("Step 8: Fetching wallet activity density...")
        print("Note: This calculates total activity to filter spray-and-pray bots")
        print()

        wallet_activity_sql_path = Path(config.QUERIES_DIR) / "wallet_activity.sql"
        if not wallet_activity_sql_path.exists():
            print(f"WARNING:  Query file not found: {wallet_activity_sql_path}")
            print("   Skipping activity density fetch.")
        else:
            wallet_activity_sql = bq.load_query_from_file(wallet_activity_sql_path)

            # Prepare parameterized query
            activity_job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter(
                        "candidate_wallet_addresses", "STRING", wallet_addresses
                    ),
                    bigquery.ScalarQueryParameter(
                        "lookback_days", "INT64", config.LOOKBACK_DAYS
                    )
                ]
            )

            print("Estimating wallet_activity query cost...")
            # Dry run estimate
            sample_addresses = wallet_addresses[:min(10, len(wallet_addresses))]
            dry_run_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter(
                        "candidate_wallet_addresses", "STRING", sample_addresses
                    ),
                    bigquery.ScalarQueryParameter(
                        "lookback_days", "INT64", config.LOOKBACK_DAYS
                    )
                ],
                dry_run=True,
                use_query_cache=False
            )

            try:
                query_job = bq.client.query(wallet_activity_sql, job_config=dry_run_config)
                bytes_scanned = query_job.total_bytes_processed
                gb_scanned = bytes_scanned / (1024**3)
                cost_usd = (bytes_scanned / (1024**4)) * config.BIGQUERY_COST_PER_TB

                # Scale to all wallets
                scaling_factor = len(wallet_addresses) / len(sample_addresses)
                estimated_total_cost = cost_usd * scaling_factor

                print(f"Estimated cost for all {len(wallet_addresses)} wallets: ${estimated_total_cost:.4f}")

                if estimated_total_cost > 0.50:
                    response = input(f"Proceed with activity density fetch? (y/n): ")
                    if response.lower() != "y":
                        print("Skipped activity density fetch.")
                    else:
                        # Execute query
                        print("Fetching activity density...")
                        activity_df = bq.client.query(
                            wallet_activity_sql, job_config=activity_job_config
                        ).to_dataframe()

                        # Save to parquet
                        output_path = Path(config.EXPORTS_DIR) / "wallet_activity.parquet"
                        activity_df.to_parquet(output_path, index=False)
                        print(f"OK: Saved {len(activity_df)} wallet activity records to {output_path}")
                else:
                    # Cost is acceptable, just execute
                    print("Fetching activity density...")
                    activity_df = bq.client.query(
                        wallet_activity_sql, job_config=activity_job_config
                    ).to_dataframe()

                    # Save
                    output_path = Path(config.EXPORTS_DIR) / "wallet_activity.parquet"
                    activity_df.to_parquet(output_path, index=False)
                    print(f"OK: Saved {len(activity_df)} wallet activity records to {output_path}")

            except Exception as e:
                print(f"WARNING:  Error fetching activity density: {e}")

    print()

    # Step 9: Fetch wallet sell behavior (identifies strategic dumpers vs holders)
    if len(first_buyers_df) > 0:
        print("Step 9: Fetching wallet sell behavior...")
        print("Note: This identifies strategic dumpers (predators) vs bag holders")
        print()

        wallet_sells_sql_path = Path(config.QUERIES_DIR) / "wallet_sells.sql"
        if not wallet_sells_sql_path.exists():
            print(f"WARNING:  Query file not found: {wallet_sells_sql_path}")
            print("   Skipping sell behavior fetch.")
        else:
            wallet_sells_sql = bq.load_query_from_file(wallet_sells_sql_path)

            # Prepare parameterized query
            sells_job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter(
                        "candidate_wallet_addresses", "STRING", wallet_addresses
                    ),
                    bigquery.ArrayQueryParameter(
                        "successful_token_addresses", "STRING", token_addresses
                    ),
                    bigquery.ScalarQueryParameter(
                        "lookback_days", "INT64", config.LOOKBACK_DAYS
                    )
                ]
            )

            print("Estimating wallet_sells query cost...")
            # Dry run estimate
            sample_addresses = wallet_addresses[:min(10, len(wallet_addresses))]
            dry_run_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter(
                        "candidate_wallet_addresses", "STRING", sample_addresses
                    ),
                    bigquery.ArrayQueryParameter(
                        "successful_token_addresses", "STRING", token_addresses
                    ),
                    bigquery.ScalarQueryParameter(
                        "lookback_days", "INT64", config.LOOKBACK_DAYS
                    )
                ],
                dry_run=True,
                use_query_cache=False
            )

            try:
                query_job = bq.client.query(wallet_sells_sql, job_config=dry_run_config)
                bytes_scanned = query_job.total_bytes_processed
                gb_scanned = bytes_scanned / (1024**3)
                cost_usd = (bytes_scanned / (1024**4)) * config.BIGQUERY_COST_PER_TB

                # Scale to all wallets
                scaling_factor = len(wallet_addresses) / len(sample_addresses)
                estimated_total_cost = cost_usd * scaling_factor

                print(f"Estimated cost for all {len(wallet_addresses)} wallets: ${estimated_total_cost:.4f}")

                if estimated_total_cost > 0.50:
                    response = input(f"Proceed with sell behavior fetch? (y/n): ")
                    if response.lower() != "y":
                        print("Skipped sell behavior fetch.")
                    else:
                        # Execute query
                        print("Fetching sell behavior...")
                        sells_df = bq.client.query(
                            wallet_sells_sql, job_config=sells_job_config
                        ).to_dataframe()

                        # Save to parquet
                        output_path = Path(config.EXPORTS_DIR) / "wallet_sells.parquet"
                        sells_df.to_parquet(output_path, index=False)
                        print(f"OK: Saved {len(sells_df)} wallet sell records to {output_path}")
                else:
                    # Cost is acceptable, just execute
                    print("Fetching sell behavior...")
                    sells_df = bq.client.query(
                        wallet_sells_sql, job_config=sells_job_config
                    ).to_dataframe()

                    # Save
                    output_path = Path(config.EXPORTS_DIR) / "wallet_sells.parquet"
                    sells_df.to_parquet(output_path, index=False)
                    print(f"OK: Saved {len(sells_df)} wallet sell records to {output_path}")

            except Exception as e:
                print(f"WARNING:  Error fetching sell behavior: {e}")

    print()

    # Step 10: Print summary
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

    print("Data files exported:")
    exports_dir = Path(config.EXPORTS_DIR)
    if (exports_dir / "successful_tokens.csv").exists():
        print(f"  OK: successful_tokens.csv (10x tokens including pumps)")
    if (exports_dir / "token_launches.parquet").exists():
        print(f"  OK: token_launches.parquet (CRITICAL - actual LP creation times)")
    if (exports_dir / "first_buyers.parquet").exists():
        print(f"  OK: first_buyers.parquet")
    if (exports_dir / "wallet_history.parquet").exists():
        print(f"  OK: wallet_history.parquet (with whale buy filter)")
    if (exports_dir / "wallet_activity.parquet").exists():
        print(f"  OK: wallet_activity.parquet")
    if (exports_dir / "wallet_sells.parquet").exists():
        print(f"  OK: wallet_sells.parquet")
    print()

    print("OK: Historical data fetch completed!")
    print("\nNext step: Run 02_analyze_wallets.py to calculate whale scores")
    print("=" * 70)

    # Close connection
    con.close()


if __name__ == "__main__":
    main()
