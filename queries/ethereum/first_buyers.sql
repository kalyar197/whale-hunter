/*
 * First Buyers Detection Query (UPDATED with Actual LP Creation Timing)
 *
 * Find wallets that consistently bought successful tokens early.
 * This is the CORE whale detection query.
 *
 * CRITICAL UPDATE: Now uses ACTUAL LP creation timestamps for accurate buy ranking.
 *
 * Strategy:
 * 1. Get actual LP creation timestamps from token_launches.sql
 * 2. For each successful token, rank all buyers by their first buy AFTER LP creation
 * 3. Take the first 100 buyers for each token (expanded to catch stealth insiders)
 * 4. Count how many successful tokens each wallet was early on
 * 5. Return wallets with >= 5 early hits
 */

WITH successful_tokens AS (
    -- IMPORTANT: This should be populated with ACTUAL 10x+ tokens
    -- from DEXScreener API (multi-timeframe verified)
    --
    -- Method 1: Use parameter (recommended)
    -- Pass token addresses via @successful_token_addresses parameter
    SELECT token_address
    FROM UNNEST(@successful_token_addresses) AS token_address
),

actual_token_launches AS (
    -- CRITICAL: Get ACTUAL LP creation timestamps (from token_launches.sql results)
    -- This ensures buy_rank is calculated from LP creation, not token minting
    SELECT
        token_address,
        launch_timestamp,
        launch_block
    FROM UNNEST(@token_launch_data) AS token_launch_data
),

first_buy_per_wallet AS (
    -- For each wallet-token pair, get their FIRST buy AFTER LP creation
    SELECT
        tt.to_address AS wallet,
        tt.token_address,
        MIN(tt.block_timestamp) AS first_buy_time,
        MIN(tt.block_number) AS first_buy_block,
        MIN(tt.transaction_index) AS first_buy_tx_index,
        SUM(CAST(tt.value AS FLOAT64)) AS total_bought
    FROM `bigquery-public-data.crypto_ethereum.token_transfers` tt
    INNER JOIN successful_tokens st ON tt.token_address = st.token_address
    INNER JOIN actual_token_launches atl ON tt.token_address = atl.token_address
    WHERE tt.block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @lookback_days DAY)
        AND tt.to_address IS NOT NULL
        AND tt.to_address != '0x0000000000000000000000000000000000000000'  -- Exclude burn address
        AND tt.value IS NOT NULL
        AND CAST(tt.value AS FLOAT64) > 0
        -- CRITICAL: Only include buys AFTER LP creation
        AND tt.block_timestamp >= atl.launch_timestamp
    GROUP BY wallet, token_address
),

ranked_buyers AS (
    -- Rank buyers by their entry time RELATIVE TO LP CREATION
    SELECT
        fb.wallet,
        fb.token_address,
        fb.first_buy_time,
        fb.first_buy_block,
        fb.first_buy_tx_index,
        fb.total_bought,
        atl.launch_timestamp,
        atl.launch_block,
        -- Calculate timing from LP creation
        TIMESTAMP_DIFF(fb.first_buy_time, atl.launch_timestamp, SECOND) AS seconds_after_launch,
        fb.first_buy_block - atl.launch_block AS blocks_after_launch,
        -- Rank buyers from LP creation (NOT from token minting)
        ROW_NUMBER() OVER (
            PARTITION BY fb.token_address
            ORDER BY fb.first_buy_time ASC, fb.first_buy_tx_index ASC
        ) AS buy_rank
    FROM first_buy_per_wallet fb
    INNER JOIN actual_token_launches atl ON fb.token_address = atl.token_address
),

early_buyers AS (
    -- Filter to first 100 buyers of each token (UPDATED from 50 to catch stealth insiders)
    -- Insiders often wait past rank 50 to blend in with retail
    SELECT *
    FROM ranked_buyers
    WHERE buy_rank <= 100  -- First 100 buyers (expanded to catch rank 51-100 insiders)
),

whale_candidates AS (
    -- Count early hits per wallet
    SELECT
        wallet,
        COUNT(DISTINCT token_address) AS early_hit_count,
        AVG(buy_rank) AS avg_buy_rank,
        AVG(seconds_after_launch) AS avg_seconds_after_launch,
        AVG(blocks_after_launch) AS avg_blocks_after_launch,
        ARRAY_AGG(STRUCT(
            token_address,
            buy_rank,
            first_buy_time,
            seconds_after_launch
        ) ORDER BY first_buy_time ASC LIMIT 20) AS token_details,
        MIN(first_buy_time) AS first_seen,
        MAX(first_buy_time) AS last_seen
    FROM early_buyers
    GROUP BY wallet
    HAVING early_hit_count >= @min_early_hits  -- Configurable threshold
)

-- Final output
SELECT
    wallet,
    early_hit_count,
    avg_buy_rank,
    avg_seconds_after_launch,
    avg_blocks_after_launch,
    first_seen,
    last_seen,
    TIMESTAMP_DIFF(last_seen, first_seen, DAY) AS active_days,
    token_details
FROM whale_candidates
ORDER BY early_hit_count DESC, avg_buy_rank ASC
LIMIT 10000;

/*
 * QUERY EXPLANATION (UPDATED with Actual LP Creation Timing):
 *
 * 1. successful_tokens: Gets list of 10x+ tokens from DEXScreener
 *    - MUST be passed via @successful_token_addresses parameter
 *    - Should be multi-timeframe verified (Option A)
 *
 * 2. actual_token_launches: Gets ACTUAL LP creation timestamps
 *    - CRITICAL: Passed via @token_launch_data from token_launches.sql
 *    - NOT using first transfer (which is token minting)
 *
 * 3. first_buy_per_wallet: Gets each wallet's first purchase AFTER LP creation
 *    - Filters to only include buys after launch_timestamp
 *    - Groups by wallet + token to find when they first entered
 *
 * 4. ranked_buyers: Ranks wallets by entry time RELATIVE TO LP CREATION
 *    - ROW_NUMBER creates buy_rank from LP creation (1 = first buyer after LP)
 *    - Orders by timestamp first, then transaction index for same-block buys
 *    - NOW ACCURATE: timing is from LP creation, not token minting
 *
 * 5. early_buyers: Filters to first 100 buyers (EXPANDED from 50)
 *    - Catches stealth insiders who wait past rank 50
 *
 * 6. whale_candidates: Aggregates to find consistent early buyers
 *    - Counts how many tokens each wallet was early on
 *    - Calculates average buy rank and timing metrics
 *    - Requires >= @min_early_hits (configurable, default 5)
 *
 * OUTPUT COLUMNS:
 * - wallet: Wallet address
 * - early_hit_count: Number of successful tokens bought early
 * - avg_buy_rank: Average position FROM LP CREATION (NOW ACCURATE)
 * - avg_seconds_after_launch: Average seconds after LP creation
 * - avg_blocks_after_launch: Average blocks after LP creation
 * - first_seen/last_seen: Activity timeframe
 * - token_details: Array of tokens with buy details + timing
 *
 * PARAMETERS:
 * - @successful_token_addresses: Array of 10x token addresses (from DEXScreener)
 * - @token_launch_data: Launch data from token_launches.sql
 * - @lookback_days: Days to look back (default: 180)
 * - @min_early_hits: Minimum early hits required (default: 5)
 *
 * PERFORMANCE NOTES:
 * - This query can scan 100-200 GB on full Ethereum history
 * - Use the estimate_query_cost() function before running!
 * - Consider limiting lookback_days to reduce costs
 *
 * CRITICAL FIXES:
 * 1. Buy rank calculated from LP creation (not token minting)
 * 2. Only includes buys AFTER LP creation
 * 3. Accurate timing metrics for pattern detection
 *
 * HOW TO USE:
 *
 * Step 1: Get 10x tokens from DEXScreener (multi-timeframe)
 * ```python
 * from src.data.dexscreener_client import DEXScreenerClient
 * client = DEXScreenerClient()
 * token_addresses = client.find_sustained_10x_tokens(chain="ethereum")
 * ```
 *
 * Step 2: Pass to BigQuery as parameter
 * ```python
 * from google.cloud import bigquery
 * job_config = bigquery.QueryJobConfig(
 *     query_parameters=[
 *         bigquery.ArrayQueryParameter(
 *             "successful_token_addresses",
 *             "STRING",
 *             token_addresses
 *         )
 *     ]
 * )
 * results = client.query(sql, job_config=job_config).to_dataframe()
 * ```
 *
 * IMPROVEMENT IDEAS:
 * - Add same-block detection (buy_block == liquidity_add_block)
 * - Filter out known DEX router addresses
 * - Add minimum buy amount threshold
 */
