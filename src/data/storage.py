import duckdb
import pandas as pd
from typing import Optional, List, Dict, Any
from config.settings import config


SCHEMA = """
-- Wallet profiles with metrics
CREATE TABLE IF NOT EXISTS wallets (
    address VARCHAR PRIMARY KEY,
    chain VARCHAR NOT NULL,
    first_seen TIMESTAMP,
    last_seen TIMESTAMP,
    total_trades INTEGER DEFAULT 0,
    early_hit_count INTEGER DEFAULT 0,
    avg_buy_rank FLOAT,
    whale_score FLOAT,
    cluster_id INTEGER,
    tags VARCHAR[],
    strategic_exit_count INTEGER DEFAULT 0,  -- NEW: Count of strategic dumps
    avg_hold_time_hours FLOAT,  -- NEW: Average time between buy and sell
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Individual transaction records (BUY and SELL)
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY,
    wallet VARCHAR NOT NULL,
    chain VARCHAR NOT NULL,
    token_address VARCHAR NOT NULL,
    action VARCHAR NOT NULL CHECK(action IN ('BUY', 'SELL')),  -- NEW: Track buys AND sells
    amount DOUBLE,
    timestamp TIMESTAMP NOT NULL,
    block_number BIGINT NOT NULL,
    tx_hash VARCHAR NOT NULL,
    tx_index INTEGER,
    buy_rank INTEGER,
    launch_timestamp TIMESTAMP,
    launch_block BIGINT,
    is_same_block_buy BOOLEAN DEFAULT FALSE,
    seconds_after_launch DOUBLE,
    blocks_after_launch INTEGER,
    FOREIGN KEY (wallet) REFERENCES wallets(address)
);

-- Token launch tracking
CREATE TABLE IF NOT EXISTS tokens (
    address VARCHAR PRIMARY KEY,
    chain VARCHAR NOT NULL,
    symbol VARCHAR,
    name VARCHAR,
    launch_timestamp TIMESTAMP,
    launch_block BIGINT,
    initial_liquidity_usd DOUBLE,
    peak_mcap_usd DOUBLE,
    current_mcap_usd DOUBLE,
    max_return_multiple DOUBLE,
    is_rugged BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Wallet clusters (connected wallets)
CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY,
    wallets VARCHAR[],
    common_funding_source VARCHAR,
    total_wallets INTEGER,
    combined_volume_usd DOUBLE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Detected suspicious patterns
CREATE TABLE IF NOT EXISTS patterns (
    id INTEGER PRIMARY KEY,
    wallet VARCHAR NOT NULL,
    pattern_name VARCHAR NOT NULL,
    severity INTEGER NOT NULL,
    description VARCHAR,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (wallet) REFERENCES wallets(address)
);

-- Whale watchlist (confirmed whales to monitor)
CREATE TABLE IF NOT EXISTS watchlist (
    wallet VARCHAR PRIMARY KEY,
    chain VARCHAR NOT NULL,
    whale_score FLOAT NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes VARCHAR,
    alert_enabled BOOLEAN DEFAULT TRUE
);

-- Create indices for faster queries
CREATE INDEX IF NOT EXISTS idx_trades_wallet ON trades(wallet);
CREATE INDEX IF NOT EXISTS idx_trades_token ON trades(token_address);
CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
CREATE INDEX IF NOT EXISTS idx_patterns_wallet ON patterns(wallet);
CREATE INDEX IF NOT EXISTS idx_wallets_score ON wallets(whale_score);
"""


def init_database(db_path: Optional[str] = None) -> duckdb.DuckDBPyConnection:
    """
    Initialize DuckDB with schema.

    Args:
        db_path: Path to database file. If None, uses config default.

    Returns:
        DuckDB connection
    """
    if db_path is None:
        db_path = config.DB_PATH

    con = duckdb.connect(db_path)
    con.execute(SCHEMA)
    print(f"Database initialized at: {db_path}")
    return con


def insert_wallet(
    con: duckdb.DuckDBPyConnection,
    address: str,
    chain: str,
    tags: Optional[List[str]] = None,
) -> None:
    """
    Insert or update a wallet record.

    Args:
        con: DuckDB connection
        address: Wallet address
        chain: Blockchain (ethereum, base, etc.)
        tags: List of tags for categorization
    """
    if tags is None:
        tags = []

    con.execute(
        """
        INSERT INTO wallets (address, chain, tags)
        VALUES (?, ?, ?)
        ON CONFLICT (address) DO UPDATE SET
            updated_at = NOW()
    """,
        [address, chain, tags],
    )


def insert_trades_bulk(con: duckdb.DuckDBPyConnection, trades_df: pd.DataFrame) -> int:
    """
    Bulk insert trade records from DataFrame.

    Args:
        con: DuckDB connection
        trades_df: DataFrame with columns: wallet, chain, token_address, action, amount,
                   timestamp, block_number, tx_hash, tx_index, buy_rank,
                   launch_timestamp, launch_block, is_same_block_buy,
                   seconds_after_launch, blocks_after_launch

    Returns:
        Number of records inserted
    """
    # Use DuckDB's native register to insert DataFrame directly
    con.register("trades_temp", trades_df)

    # Build column list dynamically based on what's in the DataFrame
    base_columns = ['wallet', 'chain', 'token_address', 'amount',
                    'timestamp', 'block_number', 'tx_hash', 'tx_index']
    optional_columns = ['action', 'buy_rank', 'launch_timestamp', 'launch_block',
                        'is_same_block_buy', 'seconds_after_launch', 'blocks_after_launch']

    columns_to_insert = base_columns.copy()
    for col in optional_columns:
        if col in trades_df.columns:
            columns_to_insert.append(col)

    # If action column doesn't exist, default to 'BUY' for backward compatibility
    if 'action' not in trades_df.columns:
        con.execute("ALTER TABLE trades_temp ADD COLUMN action VARCHAR DEFAULT 'BUY'")
        columns_to_insert.append('action')

    columns_str = ', '.join(columns_to_insert)

    result = con.execute(
        f"""
        INSERT INTO trades ({columns_str})
        SELECT {columns_str}
        FROM trades_temp
    """
    )
    con.unregister("trades_temp")
    return len(trades_df)


def get_wallet_trades(
    con: duckdb.DuckDBPyConnection, wallet_address: str
) -> pd.DataFrame:
    """
    Get all trades for a specific wallet.

    Args:
        con: DuckDB connection
        wallet_address: Wallet address to query

    Returns:
        DataFrame with trade records
    """
    return con.execute(
        """
        SELECT * FROM trades
        WHERE wallet = ?
        ORDER BY timestamp ASC
    """,
        [wallet_address],
    ).fetchdf()


def update_whale_score(
    con: duckdb.DuckDBPyConnection,
    wallet_address: str,
    score: float,
    early_hit_count: int = 0,
    avg_buy_rank: Optional[float] = None,
) -> None:
    """
    Update whale score and metrics for a wallet.

    Args:
        con: DuckDB connection
        wallet_address: Wallet address
        score: Whale score (0-100)
        early_hit_count: Number of early hits
        avg_buy_rank: Average buy rank across all trades
    """
    con.execute(
        """
        UPDATE wallets
        SET whale_score = ?,
            early_hit_count = ?,
            avg_buy_rank = ?,
            updated_at = NOW()
        WHERE address = ?
    """,
        [score, early_hit_count, avg_buy_rank, wallet_address],
    )


def insert_pattern(
    con: duckdb.DuckDBPyConnection,
    wallet_address: str,
    pattern_name: str,
    severity: int,
    description: str,
) -> None:
    """
    Insert a detected pattern for a wallet.

    Args:
        con: DuckDB connection
        wallet_address: Wallet address
        pattern_name: Name of detected pattern
        severity: Severity level (1-5)
        description: Description of the pattern
    """
    con.execute(
        """
        INSERT INTO patterns (wallet, pattern_name, severity, description)
        VALUES (?, ?, ?, ?)
    """,
        [wallet_address, pattern_name, severity, description],
    )


def add_to_watchlist(
    con: duckdb.DuckDBPyConnection,
    wallet_address: str,
    chain: str,
    whale_score: float,
    notes: Optional[str] = None,
) -> None:
    """
    Add a wallet to the watchlist.

    Args:
        con: DuckDB connection
        wallet_address: Wallet address
        chain: Blockchain
        whale_score: Whale score
        notes: Optional notes
    """
    con.execute(
        """
        INSERT INTO watchlist (wallet, chain, whale_score, notes)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (wallet) DO UPDATE SET
            whale_score = EXCLUDED.whale_score,
            notes = EXCLUDED.notes
    """,
        [wallet_address, chain, whale_score, notes],
    )


def get_top_whales(con: duckdb.DuckDBPyConnection, limit: int = 50) -> pd.DataFrame:
    """
    Get top-scoring whale wallets.

    Args:
        con: DuckDB connection
        limit: Maximum number of results

    Returns:
        DataFrame with top whale wallets
    """
    return con.execute(
        """
        SELECT
            w.address,
            w.chain,
            w.whale_score,
            w.early_hit_count,
            w.avg_buy_rank,
            w.total_trades,
            w.tags,
            ARRAY_AGG(p.pattern_name) as patterns
        FROM wallets w
        LEFT JOIN patterns p ON w.address = p.wallet
        WHERE w.whale_score IS NOT NULL
        GROUP BY w.address, w.chain, w.whale_score, w.early_hit_count, w.avg_buy_rank, w.total_trades, w.tags
        ORDER BY w.whale_score DESC
        LIMIT ?
    """,
        [limit],
    ).fetchdf()


def get_database_stats(con: duckdb.DuckDBPyConnection) -> Dict[str, int]:
    """
    Get statistics about the database contents.

    Returns:
        Dictionary with table counts
    """
    stats = {}
    tables = ["wallets", "trades", "tokens", "patterns", "watchlist"]

    for table in tables:
        count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        stats[table] = count

    return stats
