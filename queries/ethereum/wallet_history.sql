/*
 * Wallet Trade History Query
 *
 * Get detailed BUY transaction history for candidate wallets.
 * This is used for pattern detection and whale scoring.
 *
 * NOTE: Replace {WALLET_LIST} with actual comma-separated wallet addresses
 * Example: '0x123...', '0x456...', '0x789...'
 */

WITH wallet_buys AS (
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
        tt.to_address IN UNNEST(@wallet_addresses)  -- Use parameter for wallet list
        AND tt.block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 180 DAY)
        AND tt.value IS NOT NULL
        AND CAST(tt.value AS FLOAT64) > 0
        AND tt.token_address IS NOT NULL
        AND tt.token_address != '0x0000000000000000000000000000000000000000'
),

-- Get ETH value for each transaction (if available from traces)
tx_eth_values AS (
    SELECT
        tr.transaction_hash,
        SUM(CAST(tr.value AS FLOAT64)) AS eth_value
    FROM `bigquery-public-data.crypto_ethereum.traces` tr
    INNER JOIN wallet_buys wb ON tr.transaction_hash = wb.tx_hash
    WHERE tr.trace_type = 'call'
        AND tr.status = 1  -- Successful
        AND tr.value IS NOT NULL
        AND CAST(tr.value AS FLOAT64) > 0
    GROUP BY tr.transaction_hash
),

-- Get token launch times to calculate buy_rank
token_launches AS (
    SELECT
        token_address,
        MIN(block_timestamp) AS launch_timestamp,
        MIN(block_number) AS launch_block
    FROM `bigquery-public-data.crypto_ethereum.token_transfers`
    WHERE block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 180 DAY)
        AND token_address IN (
            SELECT DISTINCT token_address FROM wallet_buys
        )
    GROUP BY token_address
),

-- Calculate buy rank for each purchase
ranked_buys AS (
    SELECT
        wb.*,
        tl.launch_timestamp,
        tl.launch_block,
        TIMESTAMP_DIFF(wb.timestamp, tl.launch_timestamp, SECOND) AS seconds_after_launch,
        wb.block_number - tl.launch_block AS blocks_after_launch,
        ROW_NUMBER() OVER (
            PARTITION BY wb.token_address
            ORDER BY wb.timestamp ASC, wb.tx_index ASC
        ) AS buy_rank
    FROM wallet_buys wb
    INNER JOIN token_launches tl ON wb.token_address = tl.token_address
)

-- Final output with all buy details
SELECT
    rb.wallet,
    'ethereum' AS chain,
    rb.token_address,
    rb.amount,
    COALESCE(tev.eth_value / 1e18, 0) AS value_eth,  -- Convert from wei to ETH
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
LEFT JOIN tx_eth_values tev ON rb.tx_hash = tev.transaction_hash
ORDER BY rb.wallet, rb.timestamp ASC;

/*
 * HOW TO USE THIS QUERY:
 *
 * Option 1: Using parameterized query (recommended)
 * ```python
 * from google.cloud import bigquery
 *
 * client = bigquery.Client()
 * job_config = bigquery.QueryJobConfig(
 *     query_parameters=[
 *         bigquery.ArrayQueryParameter(
 *             "wallet_addresses",
 *             "STRING",
 *             ['0x123...', '0x456...', '0x789...']
 *         )
 *     ]
 * )
 * results = client.query(sql, job_config=job_config).to_dataframe()
 * ```
 *
 * Option 2: String replacement
 * Replace the line:
 *     tt.to_address IN UNNEST(@wallet_addresses)
 * With:
 *     tt.to_address IN ('0x123...', '0x456...', '0x789...')
 *
 * OUTPUT COLUMNS:
 * - wallet: Buyer wallet address
 * - chain: Always 'ethereum'
 * - token_address: Token contract address
 * - amount: Token amount (raw value from transfer)
 * - value_eth: ETH value of transaction
 * - timestamp: When the buy occurred
 * - block_number: Block number of buy
 * - tx_hash: Transaction hash
 * - tx_index: Transaction index in block
 * - buy_rank: Position in buyer queue (1 = first buyer)
 * - launch_timestamp/launch_block: When token launched
 * - seconds_after_launch: How quickly they bought
 * - blocks_after_launch: Blocks elapsed since launch
 * - is_same_block_buy: TRUE if bought in same block as launch (sniping)
 *
 * COST OPTIMIZATION:
 * - Only query for confirmed candidate wallets (from first_buyers.sql)
 * - Limit date range to reduce scanning
 * - Consider batching wallet queries if you have many candidates
 *
 * PATTERN DETECTION USE CASES:
 * - Count same_block_buys per wallet (liquidity sniping)
 * - Calculate avg buy_rank (consistent early buyer)
 * - Analyze seconds_after_launch distribution (bot behavior)
 * - Track total volume in value_eth (high-volume early buyer)
 */
