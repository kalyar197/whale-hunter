/*
 * Wallet Activity Density Query
 *
 * CRITICAL: Filters out "spray-and-pray" bots that buy every new token.
 *
 * Problem: A bot that buys 1000 tokens/day will inevitably hit 5 successful tokens,
 *          appearing as a "whale" despite having a 0.5% success rate.
 *
 * Solution: Calculate total activity to compute precision rate (signal-to-noise).
 *
 * Returns:
 * - total_unique_tokens: Total different tokens wallet traded
 * - total_tx_count: Total buy transactions in period
 * - Precision rate calculated later: successful_tokens / total_unique_tokens
 */

WITH candidate_wallets AS (
    -- Wallet addresses to analyze (passed as parameter)
    SELECT wallet_address
    FROM UNNEST(@candidate_wallet_addresses) AS wallet_address
),

wallet_buys AS (
    -- Get ALL buy transactions for candidates (not just successful tokens)
    SELECT
        tt.to_address AS wallet,
        tt.token_address,
        tt.block_timestamp AS timestamp,
        tt.block_number,
        tt.transaction_hash AS tx_hash
    FROM `bigquery-public-data.crypto_ethereum.token_transfers` tt
    INNER JOIN candidate_wallets cw ON tt.to_address = cw.wallet_address
    WHERE tt.block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @lookback_days DAY)
        AND tt.to_address IS NOT NULL
        AND tt.to_address != '0x0000000000000000000000000000000000000000'
        AND tt.value IS NOT NULL
        AND CAST(tt.value AS FLOAT64) > 0
)

-- Aggregate activity per wallet
SELECT
    wallet,
    COUNT(DISTINCT token_address) AS total_unique_tokens,
    COUNT(*) AS total_tx_count,
    MIN(timestamp) AS first_activity,
    MAX(timestamp) AS last_activity,
    TIMESTAMP_DIFF(MAX(timestamp), MIN(timestamp), DAY) AS activity_span_days
FROM wallet_buys
GROUP BY wallet
ORDER BY total_unique_tokens DESC;

/*
 * USAGE:
 *
 * Step 1: Get whale candidates from first_buyers.sql
 * Step 2: Pass their addresses to this query
 * Step 3: Calculate precision_rate = early_hit_count / total_unique_tokens
 *
 * Example:
 * - Wallet A: 5 early hits, 10 total tokens → 50% precision (SIGNAL)
 * - Wallet B: 5 early hits, 5000 total tokens → 0.1% precision (NOISE)
 *
 * PENALTIES:
 * - Precision < 1% + total_tokens > 500: 80% score penalty
 * - Precision < 5% + total_tokens > 200: 50% score penalty
 * - Precision < 10% + total_tokens > 100: 30% score penalty
 *
 * COST NOTES:
 * - This scans similar data to wallet_history.sql
 * - Expected cost: ~$0.10-0.25 for 100-500 candidates
 * - ALWAYS use estimate_query_cost() before running
 */
