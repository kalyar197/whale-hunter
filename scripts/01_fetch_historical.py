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
from src.data.dexscreener_client import DEXScreenerClient
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

    # Step 3: Get 10x tokens from DEXScreener (with multi-timeframe verification)
    print("Step 3: Fetching SUSTAINED 10x tokens from DEXScreener API...")
    print("Note: Using multi-timeframe verification (1h, 6h, 24h) to filter pump-and-dumps")
    print()

    dex_client = DEXScreenerClient()

    print("Querying DEXScreener for tokens with sustained gains...")
    print()

    # CRITICAL: Use multi-timeframe verification (Option A)
    successful_tokens_df = dex_client.find_sustained_10x_tokens(chain="ethereum")

    if successful_tokens_df.empty:
        print("❌ No sustained 10x tokens found from DEXScreener")
        print("This might be because:")
        print("  - No tokens currently meet the multi-timeframe criteria")
        print("  - DEXScreener API rate limit")
        print("  - Network issues")
        print("\nYou can manually provide token addresses or try again later.")
        return

    # Save successful tokens list
    successful_tokens_path = Path(config.EXPORTS_DIR) / "successful_tokens.csv"
    successful_tokens_path.parent.mkdir(parents=True, exist_ok=True)
    successful_tokens_df.to_csv(successful_tokens_path, index=False)
    print(f"✓ Saved {len(successful_tokens_df)} sustained 10x tokens to {successful_tokens_path}")
    print()

    # Get list of token addresses for BigQuery
    token_addresses = successful_tokens_df["token_address"].tolist()
    print(f"Found {len(token_addresses)} sustained token addresses to search for early buyers")
    print()

    # Step 3a: Get ACTUAL LP creation timestamps (CRITICAL FIX)
    print("Step 3a: Fetching ACTUAL LP creation timestamps...")
    print("Note: This finds when liquidity was added, not when token was minted")
    print()

    token_launches_sql_path = Path(config.QUERIES_DIR) / "token_launches.sql"
    if not token_launches_sql_path.exists():
        print(f"❌ Query file not found: {token_launches_sql_path}")
        return

    token_launches_sql = bq.load_query_from_file(token_launches_sql_path)

    # Prepare query parameters
    launches_job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter(
                "successful_token_addresses",
                "STRING",
                token_addresses
            ),
            bigquery.ScalarQueryParameter(
                "lookback_days", "INT64", config.LOOKBACK_DAYS
            )
        ]
    )

    # Estimate cost
    print("Estimating token_launches query cost...")
    dry_run_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter(
                "successful_token_addresses",
                "STRING",
                token_addresses
            ),
            bigquery.ScalarQueryParameter(
                "lookback_days", "INT64", config.LOOKBACK_DAYS
            )
        ],
        dry_run=True,
        use_query_cache=False
    )

    query_job = bq.client.query(token_launches_sql, job_config=dry_run_config)
    bytes_scanned = query_job.total_bytes_processed
    gb_scanned = bytes_scanned / (1024**3)
    cost_usd = (bytes_scanned / (1024**4)) * config.BIGQUERY_COST_PER_TB

    print(f"Query will scan {gb_scanned:.2f} GB (${cost_usd:.4f})")
    print()

    # Execute query (always proceed for small cost)
    if cost_usd > 0.10:
        response = input(f"This query will cost ${cost_usd:.4f}. Proceed? (y/n): ")
        if response.lower() != "y":
            print("Aborted by user.")
            return

    print("Fetching LP creation timestamps...")
    try:
        token_launches_df = bq.client.query(token_launches_sql, job_config=launches_job_config).to_dataframe()
        print(f"✓ Found LP creation data for {len(token_launches_df)} tokens")

        # Save to parquet
        output_path = Path(config.EXPORTS_DIR) / "token_launches.parquet"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        token_launches_df.to_parquet(output_path, index=False)
        print(f"✓ Saved to {output_path}")
    except Exception as e:
        print(f"❌ Query failed: {e}")
        return
    print()

    # Step 4: Load and estimate first_buyers query (NOW with actual LP creation data)
    print("Step 4: Analyzing first_buyers query...")
    print("Note: Now using ACTUAL LP creation timestamps for accurate buy ranking")
    print()

    first_buyers_sql_path = Path(config.QUERIES_DIR) / "first_buyers.sql"
    if not first_buyers_sql_path.exists():
        print(f"❌ Query file not found: {first_buyers_sql_path}")
        return

    first_buyers_sql = bq.load_query_from_file(first_buyers_sql_path)

    # CRITICAL: Prepare query parameters with ACTUAL LP launch data
    # Convert launch DataFrame to list of dicts for STRUCT parameter
    token_launch_data = token_launches_df[['token_address', 'launch_timestamp', 'launch_block']].to_dict('records')

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter(
                "successful_token_addresses",
                "STRING",
                token_addresses
            ),
            bigquery.ArrayQueryParameter(
                "token_launch_data",
                "STRUCT",
                token_launch_data
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
    print("Estimating query cost with successful token list and launch data...")
    dry_run_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter(
                "successful_token_addresses",
                "STRING",
                token_addresses
            ),
            bigquery.ArrayQueryParameter(
                "token_launch_data",
                "STRUCT",
                token_launch_data
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
        print(f"✓ Query completed. Retrieved {len(first_buyers_df):,} rows")

        # Save to parquet
        output_path = Path(config.EXPORTS_DIR) / "first_buyers.parquet"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        first_buyers_df.to_parquet(output_path, index=False)
        print(f"✓ Saved to {output_path}")
    except Exception as e:
        print(f"❌ Query failed: {e}")
        return
    print()

    # Step 6: Load candidate wallets into database
    print("Step 6: Loading candidate wallets into database...")
    for _, row in first_buyers_df.iterrows():
        insert_wallet(con, row["wallet"], "ethereum", tags=["early_buyer_candidate"])

    print(f"✓ Loaded {len(first_buyers_df)} candidate wallets")
    print()

    # Step 7: Fetch wallet history for candidates (if we have candidates)
    if len(first_buyers_df) > 0:
        print("Step 7: Fetching wallet trade history...")
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

            # CRITICAL: Prepare parameterized query with LP launch data AND min whale buy filter
            from google.cloud import bigquery

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter(
                        "wallet_addresses", "STRING", wallet_addresses
                    ),
                    bigquery.ArrayQueryParameter(
                        "token_launch_data",
                        "STRUCT",
                        token_launch_data
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
                        "wallet_addresses", "STRING", sample_addresses
                    ),
                    bigquery.ArrayQueryParameter(
                        "token_launch_data",
                        "STRUCT",
                        token_launch_data
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

    # Step 8: Fetch wallet activity density (CRITICAL for filtering spray-and-pray bots)
    if len(first_buyers_df) > 0:
        print("Step 8: Fetching wallet activity density...")
        print("Note: This calculates total activity to filter spray-and-pray bots")
        print()

        wallet_activity_sql_path = Path(config.QUERIES_DIR) / "wallet_activity.sql"
        if not wallet_activity_sql_path.exists():
            print(f"⚠️  Query file not found: {wallet_activity_sql_path}")
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
                        print(f"✓ Saved {len(activity_df)} wallet activity records to {output_path}")
                else:
                    # Cost is acceptable, just execute
                    print("Fetching activity density...")
                    activity_df = bq.client.query(
                        wallet_activity_sql, job_config=activity_job_config
                    ).to_dataframe()

                    # Save
                    output_path = Path(config.EXPORTS_DIR) / "wallet_activity.parquet"
                    activity_df.to_parquet(output_path, index=False)
                    print(f"✓ Saved {len(activity_df)} wallet activity records to {output_path}")

            except Exception as e:
                print(f"⚠️  Error fetching activity density: {e}")

    print()

    # Step 9: Fetch wallet sell behavior (identifies strategic dumpers vs holders)
    if len(first_buyers_df) > 0:
        print("Step 9: Fetching wallet sell behavior...")
        print("Note: This identifies strategic dumpers (predators) vs bag holders")
        print()

        wallet_sells_sql_path = Path(config.QUERIES_DIR) / "wallet_sells.sql"
        if not wallet_sells_sql_path.exists():
            print(f"⚠️  Query file not found: {wallet_sells_sql_path}")
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
                        print(f"✓ Saved {len(sells_df)} wallet sell records to {output_path}")
                else:
                    # Cost is acceptable, just execute
                    print("Fetching sell behavior...")
                    sells_df = bq.client.query(
                        wallet_sells_sql, job_config=sells_job_config
                    ).to_dataframe()

                    # Save
                    output_path = Path(config.EXPORTS_DIR) / "wallet_sells.parquet"
                    sells_df.to_parquet(output_path, index=False)
                    print(f"✓ Saved {len(sells_df)} wallet sell records to {output_path}")

            except Exception as e:
                print(f"⚠️  Error fetching sell behavior: {e}")

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
        print(f"  ✓ successful_tokens.csv (multi-timeframe verified)")
    if (exports_dir / "token_launches.parquet").exists():
        print(f"  ✓ token_launches.parquet (CRITICAL - actual LP creation times)")
    if (exports_dir / "first_buyers.parquet").exists():
        print(f"  ✓ first_buyers.parquet")
    if (exports_dir / "wallet_history.parquet").exists():
        print(f"  ✓ wallet_history.parquet (with whale buy filter)")
    if (exports_dir / "wallet_activity.parquet").exists():
        print(f"  ✓ wallet_activity.parquet")
    if (exports_dir / "wallet_sells.parquet").exists():
        print(f"  ✓ wallet_sells.parquet")
    print()

    print("✓ Historical data fetch completed!")
    print("\nNext step: Run 02_analyze_wallets.py to calculate whale scores")
    print("=" * 70)

    # Close connection
    con.close()


if __name__ == "__main__":
    main()
