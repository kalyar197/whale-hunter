/*
 * Wallet Sell Behavior Detection
 *
 * Identifies wallets that bought early and SOLD (strategic dumpers) vs.
 * wallets that bought and HELD (lucky community members).
 *
 * Strategy:
 * 1. For each candidate wallet, find their BUY transactions on successful tokens
 * 2. Find their SELL transactions on the same tokens
 * 3. Calculate hold time and sell percentage
 * 4. Detect "strategic dumper" behavior (early entry + exit)
 *
 * NOTE: We don't need exact "peak" timing. Simplified approach:
 * - If they sold >50% of their position = trader/insider
 * - If they're still holding = believer/stuck holder
 */

WITH candidate_wallets AS (
    -- Wallet addresses to analyze (passed as parameter)
    SELECT wallet_address
    FROM UNNEST(@candidate_wallet_addresses) AS wallet_address
),

successful_tokens AS (
    -- 10x tokens (from DEXScreener)
    SELECT token_address
    FROM UNNEST(@successful_token_addresses) AS token_address
),

-- Step 1: Get all BUYS on successful tokens
wallet_buys AS (
    SELECT
        tt.to_address AS wallet,
        tt.token_address,
        tt.block_timestamp AS buy_time,
        tt.block_number AS buy_block,
        SUM(CAST(tt.value AS FLOAT64)) AS total_bought
    FROM `bigquery-public-data.crypto_ethereum.token_transfers` tt
    INNER JOIN candidate_wallets cw ON tt.to_address = cw.wallet_address
    INNER JOIN successful_tokens st ON tt.token_address = st.token_address
    WHERE tt.block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @lookback_days DAY)
        AND tt.to_address IS NOT NULL
        AND tt.to_address != '0x0000000000000000000000000000000000000000'
        AND tt.value IS NOT NULL
        AND CAST(tt.value AS FLOAT64) > 0
    GROUP BY wallet, token_address, buy_time, buy_block
),

-- Step 2: Get all SELLS on successful tokens
wallet_sells AS (
    SELECT
        tt.from_address AS wallet,
        tt.token_address,
        tt.block_timestamp AS sell_time,
        tt.block_number AS sell_block,
        SUM(CAST(tt.value AS FLOAT64)) AS total_sold
    FROM `bigquery-public-data.crypto_ethereum.token_transfers` tt
    INNER JOIN candidate_wallets cw ON tt.from_address = cw.wallet_address
    INNER JOIN successful_tokens st ON tt.token_address = st.token_address
    WHERE tt.block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @lookback_days DAY)
        AND tt.from_address IS NOT NULL
        AND tt.from_address != '0x0000000000000000000000000000000000000000'
        AND tt.to_address != tt.from_address  -- Exclude self-transfers
        AND tt.value IS NOT NULL
        AND CAST(tt.value AS FLOAT64) > 0
    GROUP BY wallet, token_address, sell_time, sell_block
),

-- Step 3: Calculate buy/sell ratios per wallet-token pair
buy_sell_summary AS (
    SELECT
        COALESCE(b.wallet, s.wallet) AS wallet,
        COALESCE(b.token_address, s.token_address) AS token_address,
        COALESCE(SUM(b.total_bought), 0) AS total_bought,
        COALESCE(SUM(s.total_sold), 0) AS total_sold,
        MIN(b.buy_time) AS first_buy_time,
        MAX(s.sell_time) AS last_sell_time
    FROM wallet_buys b
    FULL OUTER JOIN wallet_sells s
        ON b.wallet = s.wallet AND b.token_address = s.token_address
    GROUP BY wallet, token_address
),

-- Step 4: Detect strategic dumpers
strategic_dumpers AS (
    SELECT
        wallet,
        token_address,
        total_bought,
        total_sold,
        first_buy_time,
        last_sell_time,
        -- Calculate sell percentage
        CASE
            WHEN total_bought > 0 THEN (total_sold / total_bought) * 100
            ELSE 0
        END AS sell_percentage,
        -- Calculate hold time in hours
        CASE
            WHEN first_buy_time IS NOT NULL AND last_sell_time IS NOT NULL
            THEN TIMESTAMP_DIFF(last_sell_time, first_buy_time, HOUR)
            ELSE NULL
        END AS hold_time_hours,
        -- Flag as strategic exit if sold >50%
        CASE
            WHEN total_bought > 0 AND (total_sold / total_bought) >= 0.5
            THEN TRUE
            ELSE FALSE
        END AS is_strategic_exit
    FROM buy_sell_summary
)

-- Final output: Aggregated per wallet
SELECT
    wallet,
    COUNT(DISTINCT token_address) AS tokens_traded,
    SUM(CASE WHEN is_strategic_exit THEN 1 ELSE 0 END) AS strategic_exit_count,
    AVG(hold_time_hours) AS avg_hold_time_hours,
    AVG(sell_percentage) AS avg_sell_percentage,
    -- Array of strategic exits for detailed analysis
    ARRAY_AGG(
        STRUCT(
            token_address,
            sell_percentage,
            hold_time_hours,
            first_buy_time,
            last_sell_time
        )
        ORDER BY sell_percentage DESC
        LIMIT 10
    ) FILTER (WHERE is_strategic_exit) AS strategic_exits
FROM strategic_dumpers
GROUP BY wallet
HAVING strategic_exit_count >= 3  -- At least 3 strategic exits
ORDER BY strategic_exit_count DESC;

/*
 * OUTPUT COLUMNS:
 * - wallet: Wallet address
 * - tokens_traded: Number of successful tokens they traded
 * - strategic_exit_count: How many times they sold >50% of position
 * - avg_hold_time_hours: Average time between buy and sell
 * - avg_sell_percentage: Average % of position sold
 * - strategic_exits: Array of detailed exit info
 *
 * INTERPRETATION:
 * - strategic_exit_count >= 3: STRATEGIC DUMPER (insider/trader)
 * - strategic_exit_count = 0: HOLDER (believer/stuck)
 * - Low avg_hold_time_hours (< 48h): QUICK FLIPPER (likely insider)
 * - High avg_sell_percentage (> 80%): COMPLETE EXIT (predator behavior)
 *
 * USAGE:
 * Step 1: Get candidates from first_buyers.sql
 * Step 2: Get successful tokens from DEXScreener
 * Step 3: Run this query to identify dumpers vs holders
 * Step 4: Prioritize wallets with high strategic_exit_count
 */
