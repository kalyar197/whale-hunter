/*
 * Wallet Trade History Query (Simplified - No LP Detection)
 *
 * Get detailed BUY transaction history for candidate wallets.
 * Used for pattern detection and whale scoring.
 *
 * SIMPLIFIED: Uses first token transfer as launch proxy (not actual LP creation)
 */

WITH successful_tokens AS (
    -- Tokens that went 4x+ (from DEXScreener/GeckoTerminal/Dune)
    SELECT DISTINCT token_address
    FROM UNNEST(@successful_token_addresses) AS token_address
),

-- Get first transfer timestamp for each token (proxy for launch)
token_first_transfer AS (
    SELECT
        token_address,
        MIN(block_timestamp) AS first_transfer_time,
        MIN(block_number) AS first_transfer_block
    FROM `bigquery-public-data.crypto_ethereum.token_transfers`
    WHERE token_address IN (SELECT token_address FROM successful_tokens)
        AND block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @lookback_days DAY)
    GROUP BY token_address
),

-- Get all buys by candidate wallets (FILTER BY TOKEN FIRST - CRITICAL FOR COST)
wallet_buys AS (
    SELECT
        tt.to_address AS wallet,
        tt.token_address,
        tt.value,
        CAST(tt.value AS FLOAT64) AS amount,
        tt.block_timestamp AS timestamp,
        tt.block_number,
        tt.transaction_hash AS tx_hash,
        tt.log_index AS tx_index
    FROM `bigquery-public-data.crypto_ethereum.token_transfers` tt
    WHERE
        -- CRITICAL: Filter by token FIRST (reduces scan from 2TB to few GB)
        tt.token_address IN (SELECT token_address FROM successful_tokens)
        AND tt.to_address IN UNNEST(@wallet_addresses)
        AND tt.block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @lookback_days DAY)
        AND tt.value IS NOT NULL
        AND CAST(tt.value AS FLOAT64) > 0
        AND tt.token_address != '0x0000000000000000000000000000000000000000'
),

-- Calculate buy rank from first transfer (no ETH filter - too expensive)
ranked_buys AS (
    SELECT
        wb.*,
        0.0 AS eth_value,  -- Placeholder (ETH value filtering removed to reduce cost)
        tft.first_transfer_time AS launch_timestamp,
        tft.first_transfer_block AS launch_block,
        TIMESTAMP_DIFF(wb.timestamp, tft.first_transfer_time, SECOND) AS seconds_after_launch,
        wb.block_number - tft.first_transfer_block AS blocks_after_launch,
        ROW_NUMBER() OVER (
            PARTITION BY wb.token_address
            ORDER BY wb.timestamp ASC, wb.block_number ASC, wb.tx_index ASC
        ) AS buy_rank
    FROM wallet_buys wb
    INNER JOIN token_first_transfer tft ON wb.token_address = tft.token_address
)

-- Final output
SELECT
    rb.wallet,
    'ethereum' AS chain,
    rb.token_address,
    rb.amount,
    rb.eth_value,
    rb.timestamp,
    rb.block_number,
    rb.tx_hash,
    rb.tx_index,
    rb.buy_rank,
    rb.launch_timestamp,
    rb.launch_block,
    rb.seconds_after_launch,
    rb.blocks_after_launch,
    -- Flag same-block buys (potential sniping)
    CASE
        WHEN rb.block_number = rb.launch_block THEN TRUE
        ELSE FALSE
    END AS is_same_block_buy
FROM ranked_buys rb
ORDER BY rb.wallet, rb.timestamp ASC;
