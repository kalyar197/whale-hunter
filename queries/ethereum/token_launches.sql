/*
 * Token Launch Detection (Actual LP Creation)
 *
 * CRITICAL FIX: Find ACTUAL token launch (LP creation) instead of first transfer.
 *
 * Problem: The first token transfer is usually minting, not trading launch.
 * Solution: Detect LP creation events from DEX factories OR first significant liquidity add.
 *
 * This query finds the actual trading launch timestamp for accurate timing metrics.
 */

WITH token_list AS (
    -- Tokens to analyze (passed as parameter)
    SELECT token_address
    FROM UNNEST(@successful_token_addresses) AS token_address
),

-- Method 1: Detect LP creation events from DEX factories
uniswap_v2_pair_creations AS (
    SELECT
        CONCAT('0x', LOWER(SUBSTR(topics[SAFE_OFFSET(1)], 27))) AS token0,
        CONCAT('0x', LOWER(SUBSTR(topics[SAFE_OFFSET(2)], 27))) AS token1,
        CONCAT('0x', LOWER(SUBSTR(data, 27, 40))) AS pair_address,
        block_timestamp AS launch_timestamp,
        block_number AS launch_block,
        'UniswapV2' AS dex_name
    FROM `bigquery-public-data.crypto_ethereum.logs`
    WHERE
        -- Uniswap V2 Factory: PairCreated(address,address,address,uint256)
        address = '0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f'
        AND topics[SAFE_OFFSET(0)] = '0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9'
        AND block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @lookback_days DAY)
),

uniswap_v3_pool_creations AS (
    SELECT
        CONCAT('0x', LOWER(SUBSTR(topics[SAFE_OFFSET(1)], 27))) AS token0,
        CONCAT('0x', LOWER(SUBSTR(topics[SAFE_OFFSET(2)], 27))) AS token1,
        CONCAT('0x', LOWER(SUBSTR(data, 27, 40))) AS pair_address,
        block_timestamp AS launch_timestamp,
        block_number AS launch_block,
        'UniswapV3' AS dex_name
    FROM `bigquery-public-data.crypto_ethereum.logs`
    WHERE
        -- Uniswap V3 Factory: PoolCreated(address,address,uint24,int24,address)
        address = '0x1F98431c8aD98523631AE4a59f267346ea31F984'
        AND topics[SAFE_OFFSET(0)] = '0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118'
        AND block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @lookback_days DAY)
),

sushiswap_pair_creations AS (
    SELECT
        CONCAT('0x', LOWER(SUBSTR(topics[SAFE_OFFSET(1)], 27))) AS token0,
        CONCAT('0x', LOWER(SUBSTR(topics[SAFE_OFFSET(2)], 27))) AS token1,
        CONCAT('0x', LOWER(SUBSTR(data, 27, 40))) AS pair_address,
        block_timestamp AS launch_timestamp,
        block_number AS launch_block,
        'Sushiswap' AS dex_name
    FROM `bigquery-public-data.crypto_ethereum.logs`
    WHERE
        -- Sushiswap Factory: PairCreated(address,address,address,uint256)
        address = '0xC0AEe478e3658e2610c5F7A4A2E1777cE9e4f2Ac'
        AND topics[SAFE_OFFSET(0)] = '0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9'
        AND block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @lookback_days DAY)
),

all_pair_creations AS (
    SELECT * FROM uniswap_v2_pair_creations
    UNION ALL
    SELECT * FROM uniswap_v3_pool_creations
    UNION ALL
    SELECT * FROM sushiswap_pair_creations
),

-- Match pairs to our token list
token_pairs_from_events AS (
    SELECT
        tl.token_address,
        pc.launch_timestamp,
        pc.launch_block,
        pc.dex_name,
        pc.pair_address
    FROM token_list tl
    INNER JOIN all_pair_creations pc
        ON tl.token_address = pc.token0 OR tl.token_address = pc.token1
),

-- Method 2: Find first significant liquidity transfer to DEX routers (fallback)
first_liquidity_add AS (
    SELECT
        tt.token_address,
        MIN(tt.block_timestamp) AS launch_timestamp,
        MIN(tt.block_number) AS launch_block,
        'FirstLiquidityAdd' AS dex_name,
        CAST(NULL AS STRING) AS pair_address
    FROM `bigquery-public-data.crypto_ethereum.token_transfers` tt
    INNER JOIN token_list tl ON tt.token_address = tl.token_address
    WHERE
        -- Transferred to known DEX router addresses
        tt.to_address IN (
            '0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D',  -- Uniswap V2 Router
            '0xE592427A0AEce92De3Edee1F18E0157C05861564',  -- Uniswap V3 Router
            '0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F',  -- Sushiswap Router
            '0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45'   -- Uniswap V3 Router 2
        )
        AND CAST(tt.value AS FLOAT64) >= 1e18  -- At least 1 token (filter dust)
        AND tt.block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @lookback_days DAY)
    GROUP BY tt.token_address
),

-- Combine both methods (prefer event-based detection)
combined_launches AS (
    SELECT
        token_address,
        launch_timestamp,
        launch_block,
        dex_name,
        pair_address,
        'pair_creation_event' AS detection_method
    FROM token_pairs_from_events

    UNION ALL

    SELECT
        token_address,
        launch_timestamp,
        launch_block,
        dex_name,
        pair_address,
        'first_liquidity_transfer' AS detection_method
    FROM first_liquidity_add
),

-- Take earliest launch per token (in case multiple DEX launches)
earliest_launch_per_token AS (
    SELECT
        token_address,
        MIN(launch_timestamp) AS launch_timestamp,
        MIN(launch_block) AS launch_block
    FROM combined_launches
    GROUP BY token_address
)

-- Final output with metadata
SELECT
    cl.token_address,
    el.launch_timestamp,
    el.launch_block,
    cl.dex_name,
    cl.pair_address,
    cl.detection_method
FROM combined_launches cl
INNER JOIN earliest_launch_per_token el
    ON cl.token_address = el.token_address
    AND cl.launch_timestamp = el.launch_timestamp
    AND cl.launch_block = el.launch_block
ORDER BY launch_timestamp DESC;

/*
 * OUTPUT COLUMNS:
 * - token_address: Token contract address
 * - launch_timestamp: ACTUAL LP creation timestamp (NOT first mint)
 * - launch_block: Block number of LP creation
 * - dex_name: Which DEX the LP was created on
 * - pair_address: LP pair contract address
 * - detection_method: How launch was detected (pair_creation_event or first_liquidity_transfer)
 *
 * USAGE:
 * This query MUST be run before wallet_history.sql to get accurate timing metrics.
 *
 * Step 1: Get successful tokens from DEXScreener
 * Step 2: Run this query to get actual launch times
 * Step 3: Use launch times in wallet_history.sql for accurate buy timing
 *
 * CRITICAL:
 * Without this, all timing metrics (seconds_after_launch, is_same_block_buy) are WRONG.
 */
