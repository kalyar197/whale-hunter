/*
 * First Buyers Detection Query (SIMPLIFIED - No LP Detection)
 *
 * Find wallets that consistently bought successful tokens early.
 * Ranks buyers from FIRST TRANSFER (not LP creation).
 * Relies on other filtering (precision rate, activity density) to filter garbage.
 */

WITH successful_tokens AS (
    SELECT token_address
    FROM UNNEST(@successful_token_addresses) AS token_address
),

-- Get first transfer timestamp for each token (proxy for launch)
token_first_transfer AS (
    SELECT
        token_address,
        MIN(block_timestamp) AS first_transfer_time
    FROM `bigquery-public-data.crypto_ethereum.token_transfers`
    WHERE token_address IN (SELECT token_address FROM successful_tokens)
        AND block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @lookback_days DAY)
    GROUP BY token_address
),

-- Get first buy for each wallet-token pair
first_buy_per_wallet AS (
    SELECT
        tt.to_address AS wallet,
        tt.token_address,
        MIN(tt.block_timestamp) AS first_buy_time,
        MIN(tt.block_number) AS first_buy_block
    FROM `bigquery-public-data.crypto_ethereum.token_transfers` tt
    INNER JOIN successful_tokens st ON tt.token_address = st.token_address
    WHERE tt.block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @lookback_days DAY)
        AND tt.to_address IS NOT NULL
        AND tt.to_address != '0x0000000000000000000000000000000000000000'
        -- Filter known DEX routers and contracts
        AND tt.to_address NOT IN (
            '0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D',  -- Uniswap V2 Router
            '0xE592427A0AEce92De3Edee1F18E0157C05861564',  -- Uniswap V3 Router
            '0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F',  -- Sushiswap Router
            '0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45'   -- Uniswap V3 Router 2
        )
    GROUP BY tt.to_address, tt.token_address
),

-- Rank buyers by first buy time (from first transfer)
ranked_buyers AS (
    SELECT
        fb.wallet,
        fb.token_address,
        fb.first_buy_time,
        fb.first_buy_block,
        tft.first_transfer_time,
        ROW_NUMBER() OVER (
            PARTITION BY fb.token_address
            ORDER BY fb.first_buy_time ASC, fb.first_buy_block ASC
        ) AS buy_rank
    FROM first_buy_per_wallet fb
    INNER JOIN token_first_transfer tft ON fb.token_address = tft.token_address
),

-- Filter to first 100 buyers per token
early_buyers AS (
    SELECT
        wallet,
        token_address,
        buy_rank,
        first_buy_time,
        first_transfer_time
    FROM ranked_buyers
    WHERE buy_rank <= 100  -- First 100 buyers
),

-- Count early hits per wallet
wallet_early_hits AS (
    SELECT
        wallet,
        COUNT(DISTINCT token_address) AS early_hit_count,
        AVG(buy_rank) AS avg_buy_rank,
        MIN(buy_rank) AS best_buy_rank,
        COUNT(*) AS total_early_buys
    FROM early_buyers
    GROUP BY wallet
    HAVING early_hit_count >= @min_early_hits  -- At least 5 early hits
)

-- Final output
SELECT
    wallet,
    early_hit_count,
    avg_buy_rank,
    best_buy_rank,
    total_early_buys
FROM wallet_early_hits
ORDER BY early_hit_count DESC, avg_buy_rank ASC
LIMIT 1000;

/*
 * OUTPUT COLUMNS:
 * - wallet: Wallet address
 * - early_hit_count: Number of successful tokens bought early
 * - avg_buy_rank: Average buy rank across all early hits
 * - best_buy_rank: Best (lowest) buy rank achieved
 * - total_early_buys: Total number of early buy transactions
 *
 * PARAMETERS:
 * - @successful_token_addresses: Array of token addresses (from Dune/DEXScreener)
 * - @lookback_days: Days to look back (default 180)
 * - @min_early_hits: Minimum early hits to qualify (default 5)
 */
