import networkx as nx
import pandas as pd
from typing import List, Dict, Any, Set, Optional
from config.settings import config


def build_wallet_graph(transfers_df: pd.DataFrame) -> nx.Graph:
    """
    Build a graph of wallet relationships based on direct transfers.

    This helps identify wallet clusters and potential Sybil attacks where
    one entity controls multiple wallets.

    Args:
        transfers_df: DataFrame with columns: from_address, to_address, value, timestamp
                     This should be ETH/token transfers BETWEEN wallets (not token buys)

    Returns:
        networkx Graph with wallets as nodes, relationships as edges
    """
    G = nx.Graph()

    if transfers_df.empty:
        return G

    # Add edges for direct transfers
    for _, tx in transfers_df.iterrows():
        if pd.notna(tx["value"]) and tx["value"] > 0:
            # Only add meaningful transfers
            G.add_edge(
                tx["from_address"],
                tx["to_address"],
                weight=tx["value"],
                timestamp=tx.get("timestamp", None),
            )

    return G


def find_wallet_clusters(
    G: nx.Graph, min_cluster_size: Optional[int] = None
) -> List[Set[str]]:
    """
    Identify clusters of connected wallets.

    Args:
        G: Network graph of wallet connections
        min_cluster_size: Minimum cluster size to return. If None, uses config default.

    Returns:
        List of wallet clusters (sets of addresses)
    """
    if min_cluster_size is None:
        min_cluster_size = config.CLUSTER_MIN_SIZE

    clusters = list(nx.connected_components(G))
    return [c for c in clusters if len(c) >= min_cluster_size]


def analyze_cluster(
    G: nx.Graph, cluster: Set[str], all_trades_df: Optional[pd.DataFrame] = None
) -> Dict[str, Any]:
    """
    Analyze a wallet cluster for suspicious patterns.

    Args:
        G: Network graph
        cluster: Set of wallet addresses in the cluster
        all_trades_df: Optional DataFrame with trade data for volume analysis

    Returns:
        Dictionary with cluster analysis
    """
    cluster_size = len(cluster)

    # Get subgraph for this cluster
    subgraph = G.subgraph(cluster)

    # Find the most connected wallet (potential funding source)
    degree_centrality = nx.degree_centrality(subgraph)
    most_connected = max(degree_centrality, key=degree_centrality.get)

    # Calculate total edges (connections between wallets)
    total_edges = subgraph.number_of_edges()

    # Analyze volume if trade data provided
    combined_volume = 0.0
    if all_trades_df is not None and "value_eth" in all_trades_df.columns:
        cluster_trades = all_trades_df[all_trades_df["wallet"].isin(cluster)]
        combined_volume = cluster_trades["value_eth"].sum()

    return {
        "cluster_size": cluster_size,
        "total_connections": total_edges,
        "most_connected_wallet": most_connected,
        "centrality_score": degree_centrality[most_connected],
        "wallets": list(cluster),
        "combined_volume_eth": float(combined_volume),
    }


def trace_funding_source(
    wallet: str, transfers_df: pd.DataFrame, max_depth: int = 5
) -> List[str]:
    """
    Trace the original funding source of a wallet by following incoming transfers.

    This helps identify if a wallet was funded by a known entity or exchange.

    Args:
        wallet: Wallet address to trace
        transfers_df: DataFrame with transfer data (columns: from_address, to_address, timestamp, value)
        max_depth: Maximum hops to trace backwards

    Returns:
        List representing funding path: [source_wallet, ..., target_wallet]
    """
    if transfers_df.empty:
        return [wallet]

    path = [wallet]
    current = wallet

    for _ in range(max_depth):
        # Find incoming transfers to current wallet
        incoming = transfers_df[transfers_df["to_address"] == current]

        if incoming.empty:
            break

        # Get the first significant funder (sorted by timestamp)
        incoming_sorted = incoming.sort_values("timestamp")
        funder = incoming_sorted.iloc[0]["from_address"]

        # Avoid cycles
        if funder in path:
            break

        path.insert(0, funder)
        current = funder

    return path


def detect_common_funding_source(wallets: List[str], transfers_df: pd.DataFrame) -> Optional[str]:
    """
    Detect if a list of wallets share a common funding source.

    Args:
        wallets: List of wallet addresses to analyze
        transfers_df: Transfer data

    Returns:
        Common funding source address if found, None otherwise
    """
    if len(wallets) < 2:
        return None

    # Trace funding for each wallet
    funding_paths = {}
    for wallet in wallets:
        path = trace_funding_source(wallet, transfers_df, max_depth=3)
        if len(path) > 1:
            # Source is the first address in the path
            funding_paths[wallet] = path[0]

    if not funding_paths:
        return None

    # Find most common funding source
    sources = list(funding_paths.values())
    from collections import Counter

    source_counts = Counter(sources)

    # Return source if it funded at least half the wallets
    most_common_source, count = source_counts.most_common(1)[0]
    if count >= len(wallets) * 0.5:
        return most_common_source

    return None


def identify_coordinated_trading(
    cluster_wallets: List[str], trades_df: pd.DataFrame, time_window_seconds: int = 300
) -> Dict[str, Any]:
    """
    Identify if wallets in a cluster are trading in a coordinated manner.

    Args:
        cluster_wallets: List of wallets in the cluster
        trades_df: Trade history for all wallets
        time_window_seconds: Time window to consider as "coordinated" (default 5 minutes)

    Returns:
        Dictionary with coordination metrics
    """
    if trades_df.empty:
        return {
            "coordinated_trades": 0,
            "coordination_score": 0,
            "examples": [],
        }

    # Filter to cluster wallets
    cluster_trades = trades_df[trades_df["wallet"].isin(cluster_wallets)].copy()

    if cluster_trades.empty:
        return {
            "coordinated_trades": 0,
            "coordination_score": 0,
            "examples": [],
        }

    # Ensure timestamp is datetime
    cluster_trades["timestamp"] = pd.to_datetime(cluster_trades["timestamp"])

    # Group by token and find trades within time window
    coordinated_count = 0
    examples = []

    for token in cluster_trades["token_address"].unique():
        token_trades = cluster_trades[cluster_trades["token_address"] == token].sort_values(
            "timestamp"
        )

        if len(token_trades) < 2:
            continue

        # Check if multiple wallets traded within time window
        for i in range(len(token_trades) - 1):
            current_trade = token_trades.iloc[i]
            next_trade = token_trades.iloc[i + 1]

            time_diff = (next_trade["timestamp"] - current_trade["timestamp"]).total_seconds()

            if time_diff <= time_window_seconds:
                coordinated_count += 1
                if len(examples) < 5:  # Keep top 5 examples
                    examples.append(
                        {
                            "token": token,
                            "wallet1": current_trade["wallet"],
                            "wallet2": next_trade["wallet"],
                            "time_diff_seconds": time_diff,
                            "timestamp": current_trade["timestamp"],
                        }
                    )

    # Calculate coordination score
    total_trades = len(cluster_trades)
    coordination_score = (coordinated_count / total_trades * 100) if total_trades > 0 else 0

    return {
        "coordinated_trades": coordinated_count,
        "coordination_score": float(coordination_score),
        "examples": examples,
    }
