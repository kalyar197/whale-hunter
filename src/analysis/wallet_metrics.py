import pandas as pd
from datetime import datetime, timezone
from typing import Dict, Any


def calculate_wallet_metrics(trades_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Calculate basic wallet metrics from trade history.

    NO win rate calculation - we only care about pattern matching, not profitability.

    Args:
        trades_df: DataFrame with columns: wallet, token_address, amount,
                   timestamp, block_number, buy_rank, is_same_block_buy

    Returns:
        Dictionary with wallet metrics:
            - wallet_address: Wallet address
            - total_trades: Total number of buy transactions
            - unique_tokens: Number of different tokens traded
            - first_trade_date: When wallet became active
            - last_trade_date: Most recent trade
            - wallet_age_days: Days since first transaction
            - tokens_traded: List of token addresses
    """
    if trades_df.empty:
        return {
            "wallet_address": None,
            "total_trades": 0,
            "unique_tokens": 0,
            "first_trade_date": None,
            "last_trade_date": None,
            "wallet_age_days": 0,
            "tokens_traded": [],
        }

    # Make a copy to avoid mutating the input DataFrame
    trades_df = trades_df.copy()

    # Ensure timestamp is datetime
    if not pd.api.types.is_datetime64_any_dtype(trades_df["timestamp"]):
        trades_df["timestamp"] = pd.to_datetime(trades_df["timestamp"])

    wallet_address = trades_df["wallet"].iloc[0] if len(trades_df) > 0 else None
    first_trade_date = trades_df["timestamp"].min()
    last_trade_date = trades_df["timestamp"].max()

    # Calculate wallet age
    if pd.notna(first_trade_date):
        wallet_age_days = (datetime.now(timezone.utc) - first_trade_date).days
    else:
        wallet_age_days = 0

    # Get unique tokens
    unique_tokens = trades_df["token_address"].nunique()
    tokens_traded = trades_df["token_address"].unique().tolist()

    return {
        "wallet_address": wallet_address,
        "total_trades": len(trades_df),
        "unique_tokens": unique_tokens,
        "first_trade_date": first_trade_date,
        "last_trade_date": last_trade_date,
        "wallet_age_days": wallet_age_days,
        "tokens_traded": tokens_traded,
    }


def get_wallet_summary_stats(trades_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Get summary statistics about a wallet's trading behavior.

    Args:
        trades_df: DataFrame with trade history

    Returns:
        Dictionary with summary stats
    """
    if trades_df.empty:
        return {}

    # Make a copy to avoid mutating the input DataFrame
    trades_df = trades_df.copy()

    # Ensure timestamp is datetime
    if not pd.api.types.is_datetime64_any_dtype(trades_df["timestamp"]):
        trades_df["timestamp"] = pd.to_datetime(trades_df["timestamp"])

    # Group by token to see trading frequency
    tokens_by_frequency = (
        trades_df.groupby("token_address")
        .size()
        .sort_values(ascending=False)
        .head(10)
        .to_dict()
    )

    # Calculate time between trades
    trades_sorted = trades_df.sort_values("timestamp")
    time_diffs = trades_sorted["timestamp"].diff().dt.total_seconds() / 3600  # hours

    avg_time_between_trades = time_diffs.mean() if len(time_diffs) > 1 else 0

    # Distribution of buy ranks
    buy_rank_stats = {}
    if "buy_rank" in trades_df and trades_df["buy_rank"].notna().any():
        buy_rank_stats = {
            "min_buy_rank": int(trades_df["buy_rank"].min()),
            "max_buy_rank": int(trades_df["buy_rank"].max()),
            "median_buy_rank": float(trades_df["buy_rank"].median()),
            "mean_buy_rank": float(trades_df["buy_rank"].mean()),
        }

    return {
        "top_tokens_by_frequency": tokens_by_frequency,
        "avg_hours_between_trades": float(avg_time_between_trades),
        "buy_rank_distribution": buy_rank_stats,
    }
