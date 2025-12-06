import pandas as pd
from typing import Dict, Any, List
from config.settings import config


def analyze_early_buying_pattern(
    wallet_trades_df: pd.DataFrame, successful_tokens: List[str] = None
) -> Dict[str, Any]:
    """
    Analyze a wallet's early buying patterns.

    Args:
        wallet_trades_df: DataFrame with trade history for one wallet
                         Must include: token_address, buy_rank, is_same_block_buy,
                         value_eth, timestamp, blocks_after_launch
        successful_tokens: Optional list of token addresses that pumped 10x+
                          If None, treats all tokens as potentially successful

    Returns:
        Dictionary with early buying metrics:
            - early_hits: Count of successful tokens bought in first 50
            - avg_buy_rank: Average position in buyer queue
            - median_buy_rank: Median buy rank
            - same_block_buys: Count of same-block buys (sniping)
            - high_volume_early_buys: Count of large early buys (>1 ETH in first 50)
            - fastest_buy_seconds: Quickest time after launch
            - avg_buy_delay_seconds: Average time after launch
            - early_buy_tokens: List of tokens bought early
    """
    if wallet_trades_df.empty:
        return {
            "early_hits": 0,
            "avg_buy_rank": 0,
            "median_buy_rank": 0,
            "same_block_buys": 0,
            "high_volume_early_buys": 0,
            "fastest_buy_seconds": 0,
            "avg_buy_delay_seconds": 0,
            "early_buy_tokens": [],
        }

    # Filter to early buys only (first N buyers)
    early_buys = wallet_trades_df[
        wallet_trades_df["buy_rank"] <= config.FIRST_N_BUYERS
    ].copy()

    if early_buys.empty:
        return {
            "early_hits": 0,
            "avg_buy_rank": 0,
            "median_buy_rank": 0,
            "same_block_buys": 0,
            "high_volume_early_buys": 0,
            "fastest_buy_seconds": 0,
            "avg_buy_delay_seconds": 0,
            "early_buy_tokens": [],
        }

    # Count early hits
    if successful_tokens:
        # Only count early buys on successful tokens
        early_hits = early_buys[
            early_buys["token_address"].isin(successful_tokens)
        ]["token_address"].nunique()
        early_buy_tokens = early_buys[
            early_buys["token_address"].isin(successful_tokens)
        ]["token_address"].unique().tolist()
    else:
        # Count all early buys
        early_hits = early_buys["token_address"].nunique()
        early_buy_tokens = early_buys["token_address"].unique().tolist()

    # Calculate buy rank statistics
    avg_buy_rank = early_buys["buy_rank"].mean()
    median_buy_rank = early_buys["buy_rank"].median()

    # Count same-block buys (liquidity sniping)
    same_block_buys = 0
    if "is_same_block_buy" in early_buys.columns:
        same_block_buys = early_buys["is_same_block_buy"].sum()

    # Count high-volume early buys
    high_volume_early_buys = 0
    if "value_eth" in early_buys.columns:
        high_volume_early_buys = (
            early_buys["value_eth"] >= config.HIGH_VOLUME_THRESHOLD_ETH
        ).sum()

    # Timing analysis
    fastest_buy_seconds = 0
    avg_buy_delay_seconds = 0
    if "seconds_after_launch" in early_buys.columns:
        timing_data = early_buys[early_buys["seconds_after_launch"].notna()]
        if not timing_data.empty:
            fastest_buy_seconds = timing_data["seconds_after_launch"].min()
            avg_buy_delay_seconds = timing_data["seconds_after_launch"].mean()

    return {
        "early_hits": int(early_hits),
        "avg_buy_rank": float(avg_buy_rank),
        "median_buy_rank": float(median_buy_rank),
        "same_block_buys": int(same_block_buys),
        "high_volume_early_buys": int(high_volume_early_buys),
        "fastest_buy_seconds": float(fastest_buy_seconds),
        "avg_buy_delay_seconds": float(avg_buy_delay_seconds),
        "early_buy_tokens": early_buy_tokens,
    }


def identify_sniping_behavior(wallet_trades_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Identify potential bot/sniping behavior.

    Args:
        wallet_trades_df: Trade history for one wallet

    Returns:
        Dictionary with sniping indicators
    """
    if wallet_trades_df.empty:
        return {
            "is_likely_sniper": False,
            "sniping_score": 0,
            "evidence": [],
        }

    # Make a copy to avoid mutating the input DataFrame
    wallet_trades_df = wallet_trades_df.copy()

    evidence = []
    sniping_score = 0

    # Check for same-block buys
    if "is_same_block_buy" in wallet_trades_df.columns:
        same_block_count = wallet_trades_df["is_same_block_buy"].sum()
        if same_block_count >= config.LIQUIDITY_SNIPER_MIN_HITS:
            evidence.append(
                f"Same-block liquidity sniping: {same_block_count} times"
            )
            sniping_score += 30

    # Check for extremely fast buys (< 60 seconds after launch)
    if "seconds_after_launch" in wallet_trades_df.columns:
        ultra_fast_buys = (wallet_trades_df["seconds_after_launch"] < 60).sum()
        if ultra_fast_buys >= 3:
            evidence.append(f"Ultra-fast buys (<60s): {ultra_fast_buys} times")
            sniping_score += 20

    # Check for consistent early ranks (always in first 10)
    if "buy_rank" in wallet_trades_df.columns:
        very_early_buys = (wallet_trades_df["buy_rank"] <= 10).sum()
        if very_early_buys >= 5:
            evidence.append(f"Consistent top-10 buyer: {very_early_buys} times")
            sniping_score += 25

    # Check for high-frequency trading (many buys in short time)
    if "timestamp" in wallet_trades_df.columns:
        wallet_trades_df["timestamp"] = pd.to_datetime(wallet_trades_df["timestamp"])
        time_span_days = (
            wallet_trades_df["timestamp"].max() - wallet_trades_df["timestamp"].min()
        ).days
        if time_span_days > 0:
            trades_per_day = len(wallet_trades_df) / time_span_days
            if trades_per_day >= 5:
                evidence.append(f"High-frequency: {trades_per_day:.1f} trades/day")
                sniping_score += 15

    is_likely_sniper = sniping_score >= 40

    return {
        "is_likely_sniper": is_likely_sniper,
        "sniping_score": sniping_score,
        "evidence": evidence,
    }


def get_top_early_tokens(
    wallet_trades_df: pd.DataFrame, limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Get the tokens this wallet was earliest on.

    Args:
        wallet_trades_df: Trade history
        limit: Max tokens to return

    Returns:
        List of dicts with token info sorted by buy rank
    """
    if wallet_trades_df.empty or "buy_rank" not in wallet_trades_df.columns:
        return []

    # Get earliest buy per token
    earliest_per_token = (
        wallet_trades_df.sort_values("buy_rank")
        .groupby("token_address")
        .first()
        .reset_index()
    )

    # Sort by buy rank and limit
    top_tokens = earliest_per_token.nsmallest(limit, "buy_rank")

    result = []
    for _, row in top_tokens.iterrows():
        token_info = {
            "token_address": row["token_address"],
            "buy_rank": int(row["buy_rank"]),
            "timestamp": row["timestamp"],
        }

        if "value_eth" in row:
            token_info["value_eth"] = float(row["value_eth"])

        if "is_same_block_buy" in row:
            token_info["is_same_block_buy"] = bool(row["is_same_block_buy"])

        result.append(token_info)

    return result
