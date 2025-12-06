/*
 * First Buyers Detection Query
 *
 * Find wallets that consistently bought successful tokens early.
 * This is the CORE whale detection query.
 *
 * Strategy:
 * 1. For each successful token, rank all buyers by their first buy timestamp
 * 2. Take the first 50 buyers for each token
 * 3. Count how many successful tokens each wallet was early on
 * 4. Return wallets with >= 5 early hits
 */

WITH successful_tokens AS (
    -- REPLACE THIS WITH RESULTS FROM token_performance.sql
    -- For now, using transfer activity as proxy for successful tokens
    SELECT DISTINCT token_address
    FROM `bigquery-public-data.crypto_ethereum.token_transfers`
    WHERE block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 180 DAY)
        AND token_address IS NOT NULL
    GROUP BY token_address
    HAVING COUNT(DISTINCT to_address) >= 100  -- At least 100 unique buyers
        AND COUNT(*) >= 1000  -- At least 1000 transfers
    LIMIT 1000  -- Limit to top 1000 most active tokens
),

first_buy_per_wallet AS (
    -- For each wallet-token pair, get their FIRST buy
    SELECT
        tt.to_address AS wallet,
        tt.token_address,
        MIN(tt.block_timestamp) AS first_buy_time,
        MIN(tt.block_number) AS first_buy_block,
        MIN(tt.transaction_index) AS first_buy_tx_index,
        SUM(CAST(tt.value AS FLOAT64)) AS total_bought
    FROM `bigquery-public-data.crypto_ethereum.token_transfers` tt
    INNER JOIN successful_tokens st ON tt.token_address = st.token_address
    WHERE tt.block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 180 DAY)
        AND tt.to_address IS NOT NULL
        AND tt.to_address != '0x0000000000000000000000000000000000000000'  -- Exclude burn address
        AND tt.value IS NOT NULL
        AND CAST(tt.value AS FLOAT64) > 0
    GROUP BY wallet, token_address
),

ranked_buyers AS (
    -- Rank buyers by their entry time for each token
    SELECT
        wallet,
        token_address,
        first_buy_time,
        first_buy_block,
        first_buy_tx_index,
        total_bought,
        ROW_NUMBER() OVER (
            PARTITION BY token_address
            ORDER BY first_buy_time ASC, first_buy_tx_index ASC
        ) AS buy_rank
    FROM first_buy_per_wallet
),

early_buyers AS (
    -- Filter to only first 50 buyers of each token
    SELECT *
    FROM ranked_buyers
    WHERE buy_rank <= 50  -- First 50 buyers
),

whale_candidates AS (
    -- Count early hits per wallet
    SELECT
        wallet,
        COUNT(DISTINCT token_address) AS early_hit_count,
        AVG(buy_rank) AS avg_buy_rank,
        ARRAY_AGG(STRUCT(
            token_address,
            buy_rank,
            first_buy_time
        ) ORDER BY first_buy_time ASC LIMIT 20) AS token_details,
        MIN(first_buy_time) AS first_seen,
        MAX(first_buy_time) AS last_seen
    FROM early_buyers
    GROUP BY wallet
    HAVING early_hit_count >= 5  -- At least 5 early hits
)

-- Final output
SELECT
    wallet,
    early_hit_count,
    avg_buy_rank,
    first_seen,
    last_seen,
    TIMESTAMP_DIFF(last_seen, first_seen, DAY) AS active_days,
    token_details
FROM whale_candidates
ORDER BY early_hit_count DESC, avg_buy_rank ASC
LIMIT 10000;

/*
 * QUERY EXPLANATION:
 *
 * 1. successful_tokens: Identifies high-activity tokens (proxy for successful pumps)
 *    - In production, replace with actual 10x+ tokens from token_performance.sql
 *
 * 2. first_buy_per_wallet: Gets each wallet's first purchase of each token
 *    - Groups by wallet + token to find when they first entered
 *
 * 3. ranked_buyers: Ranks wallets by entry time for each token
 *    - ROW_NUMBER creates buy_rank (1 = first buyer, 2 = second buyer, etc.)
 *    - Orders by timestamp first, then transaction index for same-block buys
 *
 * 4. early_buyers: Filters to first 50 buyers only
 *    - These are the "early" buyers we're tracking
 *
 * 5. whale_candidates: Aggregates to find consistent early buyers
 *    - Counts how many tokens each wallet was early on
 *    - Calculates average buy rank (lower = more consistent)
 *    - Requires >= 5 early hits (configurable threshold)
 *
 * OUTPUT COLUMNS:
 * - wallet: Wallet address
 * - early_hit_count: Number of successful tokens bought early
 * - avg_buy_rank: Average position in buyer queue (lower is better)
 * - first_seen/last_seen: Activity timeframe
 * - token_details: Array of tokens with buy details
 *
 * PERFORMANCE NOTES:
 * - This query can scan 50-100 GB on full Ethereum history
 * - Use the estimate_query_cost() function before running!
 * - Consider limiting to recent date ranges to reduce costs
 *
 * IMPROVEMENT IDEAS:
 * - Add same-block detection (buy_block == liquidity_add_block)
 * - Filter out known DEX router addresses
 * - Add minimum buy amount threshold
 * - Join with token price data to only include actual 10x+ tokens
 */
