/*
 * Token Performance Analysis Query
 *
 * IMPORTANT LIMITATION:
 * This query DOES NOT actually calculate 10x returns. It uses transfer activity
 * as a PROXY for successful tokens. This is because BigQuery public datasets
 * don't include DEX price data needed to calculate actual returns.
 *
 * To properly detect 10x tokens, you need:
 * 1. DEX pair creation events (Uniswap V2/V3, Sushiswap)
 * 2. Initial liquidity add price
 * 3. Historical price data from swap events
 * 4. Calculate: max_return = peak_price / initial_price
 *
 * Alternative approaches:
 * - Use Dune Analytics (has pre-indexed DEX data with prices)
 * - Use The Graph protocol
 * - Use external price APIs (CoinGecko, DexScreener)
 * - Decode Uniswap swap events manually from traces/logs
 *
 * For now, this query identifies highly active tokens which you can
 * then manually verify for 10x+ returns using external tools.
 */

WITH token_launch_times AS (
    -- Get first transfer time for each token (approximate launch time)
    SELECT
        token_address,
        MIN(block_timestamp) AS launch_timestamp,
        MIN(block_number) AS launch_block,
        COUNT(DISTINCT to_address) AS unique_holders
    FROM `bigquery-public-data.crypto_ethereum.token_transfers`
    WHERE block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 180 DAY)
        AND token_address IS NOT NULL
    GROUP BY token_address
    HAVING COUNT(DISTINCT to_address) >= 50  -- Filter out very low activity tokens
),

token_activity AS (
    -- Get transfer activity metrics for each token
    SELECT
        token_address,
        COUNT(*) AS total_transfers,
        COUNT(DISTINCT from_address) AS unique_senders,
        COUNT(DISTINCT to_address) AS unique_receivers,
        MAX(block_timestamp) AS last_activity
    FROM `bigquery-public-data.crypto_ethereum.token_transfers`
    WHERE block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 180 DAY)
        AND token_address IS NOT NULL
    GROUP BY token_address
)

-- Combine launch times with activity metrics
SELECT
    lt.token_address,
    lt.launch_timestamp,
    lt.launch_block,
    lt.unique_holders AS initial_holders,
    ta.total_transfers,
    ta.unique_senders,
    ta.unique_receivers,
    ta.last_activity,
    TIMESTAMP_DIFF(ta.last_activity, lt.launch_timestamp, DAY) AS active_days
FROM token_launch_times lt
INNER JOIN token_activity ta ON lt.token_address = ta.token_address
WHERE
    -- Filter for tokens with good activity (likely successful)
    ta.total_transfers >= 1000  -- At least 1000 transfers
    AND ta.unique_receivers >= 100  -- At least 100 unique buyers
    AND lt.unique_holders >= 50  -- Started with decent holder base
ORDER BY ta.total_transfers DESC
LIMIT 5000;

/*
 * IMPORTANT NOTES:
 *
 * 1. This query is a STARTING POINT and uses transfer count as a proxy for success.
 *    In production, you should join with DEX pair data to calculate actual returns:
 *    - Uniswap V2/V3 pair creation and swap events
 *    - Initial liquidity and price data
 *    - Peak price achieved
 *    - Calculate max_return_multiple = peak_price / initial_price
 *
 * 2. To get accurate DEX data, you would query tables like:
 *    - bigquery-public-data.crypto_ethereum.traces (for contract calls)
 *    - Decoded Uniswap events for SwapTokensForExactETH, etc.
 *
 * 3. Alternative approach: Use a service like Dune Analytics or The Graph
 *    that has pre-indexed DEX data with price information.
 *
 * 4. For now, this query identifies highly active tokens in the last 180 days,
 *    which you can then manually verify for 10x+ returns using external tools.
 */
