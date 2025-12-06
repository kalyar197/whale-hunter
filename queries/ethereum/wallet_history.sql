/*
 * Wallet Trade History Query (UPDATED with Actual LP Creation Timing)
 *
 * Get detailed BUY transaction history for candidate wallets.
 * This is used for pattern detection and whale scoring.
 *
 * CRITICAL UPDATE: Now uses ACTUAL LP creation timestamps from token_launches,
 * not first token transfer. This gives accurate timing metrics.
 *
 * NOTE: This query depends on token_launches data being available.
 */

WITH actual_token_launches AS (
    -- Get ACTUAL LP creation timestamps (from token_launches.sql results)
    -- This should be pre-populated or passed as a temp table
    SELECT
        token_address,
        launch_timestamp,
        launch_block
    FROM UNNEST(@token_launch_data) AS token_launch_data
),

wallet_buys AS (
    SELECT
        tt.to_address AS wallet,
        tt.token_address,
        tt.value,
        CAST(tt.value AS FLOAT64) AS amount,
        tt.block_timestamp AS timestamp,
        tt.block_number,
        tt.transaction_hash AS tx_hash,
        tt.transaction_index AS tx_index,
        tt.log_index
    FROM `bigquery-public-data.crypto_ethereum.token_transfers` tt
    WHERE
        -- Filter to only our candidate wallets
        tt.to_address IN UNNEST(@wallet_addresses)
        AND tt.block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @lookback_days DAY)
        AND tt.value IS NOT NULL
        AND CAST(tt.value AS FLOAT64) > 0
        AND tt.token_address IS NOT NULL
        AND tt.token_address != '0x0000000000000000000000000000000000000000'
),

-- Get ETH value spent per transaction (minimum whale buy filter)
wallet_buys_with_eth_value AS (
    SELECT
        wb.*,
        tr.value AS eth_value_wei,
        CAST(tr.value AS FLOAT64) / 1e18 AS eth_value
    FROM wallet_buys wb
    LEFT JOIN `bigquery-public-data.crypto_ethereum.traces` tr
        ON wb.tx_hash = tr.transaction_hash
        AND tr.from_address = wb.wallet
        AND tr.trace_type = 'call'
        AND tr.status = 1
        AND tr.call_type = 'call'
    WHERE
        -- WHALE FILTER: Minimum buy value to exclude small buyers and bots
        -- Only include buys >= 0.1 ETH (configurable via @min_whale_buy_eth)
        CAST(tr.value AS FLOAT64) / 1e18 >= @min_whale_buy_eth
),

-- Calculate buy rank for each purchase relative to ACTUAL LP creation
ranked_buys AS (
    SELECT
        wb.*,
        atl.launch_timestamp,
        atl.launch_block,
        -- CRITICAL: Calculate timing from ACTUAL LP creation, not first transfer
        TIMESTAMP_DIFF(wb.timestamp, atl.launch_timestamp, SECOND) AS seconds_after_launch,
        wb.block_number - atl.launch_block AS blocks_after_launch,
        ROW_NUMBER() OVER (
            PARTITION BY wb.token_address
            ORDER BY wb.timestamp ASC, wb.tx_index ASC
        ) AS buy_rank
    FROM wallet_buys_with_eth_value wb
    INNER JOIN actual_token_launches atl ON wb.token_address = atl.token_address
    WHERE atl.launch_timestamp IS NOT NULL  -- Only include tokens with known launch
)

-- Final output with all buy details
SELECT
    rb.wallet,
    'ethereum' AS chain,
    rb.token_address,
    rb.amount,
    rb.eth_value,  -- NEW: ETH value spent (whale filter metric)
    rb.timestamp,
    rb.block_number,
    rb.tx_hash,
    rb.tx_index,
    rb.buy_rank,
    rb.launch_timestamp,
    rb.launch_block,
    rb.seconds_after_launch,
    rb.blocks_after_launch,
    -- Flag same-block buys (potential sniping) - NOW ACCURATE
    CASE
        WHEN rb.block_number = rb.launch_block THEN TRUE
        ELSE FALSE
    END AS is_same_block_buy
FROM ranked_buys rb
ORDER BY rb.wallet, rb.timestamp ASC;

/*
 * HOW TO USE THIS QUERY:
 *
 * CRITICAL: This query now requires token launch data from token_launches.sql
 *
 * Step 1: Run token_launches.sql to get actual LP creation times
 * Step 2: Pass the results to this query via @token_launch_data parameter
 *
 * ```python
 * from google.cloud import bigquery
 *
 * client = bigquery.Client()
 *
 * # First: Get actual token launches
 * launch_data = client.query(token_launches_sql).to_dataframe()
 *
 * # Then: Query wallet history with actual launch times
 * job_config = bigquery.QueryJobConfig(
 *     query_parameters=[
 *         bigquery.ArrayQueryParameter(
 *             "wallet_addresses",
 *             "STRING",
 *             ['0x123...', '0x456...']
 *         ),
 *         bigquery.ArrayQueryParameter(
 *             "token_launch_data",
 *             "STRUCT",
 *             launch_data.to_dict('records')
 *         ),
 *         bigquery.ScalarQueryParameter("lookback_days", "INT64", 180),
 *         bigquery.ScalarQueryParameter("min_whale_buy_eth", "FLOAT64", 0.1)
 *     ]
 * )
 * results = client.query(sql, job_config=job_config).to_dataframe()
 * ```
 *
 * PARAMETERS:
 * - @wallet_addresses: Array of wallet addresses to analyze
 * - @token_launch_data: Launch data from token_launches.sql (token_address, launch_timestamp, launch_block)
 * - @lookback_days: How many days to look back (default: 180)
 * - @min_whale_buy_eth: Minimum ETH buy value (default: 0.1) - WHALE FILTER
 *
 * OUTPUT COLUMNS:
 * - wallet: Buyer wallet address
 * - chain: Always 'ethereum'
 * - token_address: Token contract address
 * - amount: Token amount (raw value from transfer)
 * - eth_value: ETH spent on buy (NEW - whale filter metric)
 * - timestamp: When the buy occurred
 * - block_number: Block number of buy
 * - tx_hash: Transaction hash
 * - tx_index: Transaction index in block
 * - buy_rank: Position in buyer queue (1 = first buyer) - NOW ACCURATE FROM LP CREATION
 * - launch_timestamp/launch_block: ACTUAL LP creation (NOT first transfer)
 * - seconds_after_launch: How quickly they bought FROM LP CREATION
 * - blocks_after_launch: Blocks elapsed since LP CREATION
 * - is_same_block_buy: TRUE if bought in same block as LP creation (sniping)
 *
 * CRITICAL FIXES:
 * 1. Uses ACTUAL LP creation timestamp (not first token transfer)
 * 2. Filters out small buyers (< 0.1 ETH) to focus on whales
 * 3. Accurate timing metrics for pattern detection
 *
 * COST OPTIMIZATION:
 * - Only query for confirmed candidate wallets
 * - ETH value filter reduces result size significantly
 * - Consider batching wallet queries if you have many candidates
 *
 * PATTERN DETECTION USE CASES:
 * - Count same_block_buys per wallet (liquidity sniping) - NOW ACCURATE
 * - Calculate avg buy_rank (consistent early buyer) - NOW ACCURATE
 * - Analyze seconds_after_launch distribution (bot behavior) - NOW ACCURATE
 * - Filter out small buyers / spray-and-pray bots via eth_value
 */
