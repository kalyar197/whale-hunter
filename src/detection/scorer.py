from typing import Dict, Any, List
import math
from src.detection.patterns import SuspiciousPattern
from config.settings import config


def calculate_early_hit_score_logarithmic(early_hits: int) -> float:
    """
    Logarithmic scaling for early hits (diminishing returns).

    Avoids arbitrary thresholds. Uses natural logarithm for smooth scaling.

    1 hit = ~10 points
    5 hits = ~32 points
    10 hits = ~43 points
    20 hits = 50 points (cap)

    Args:
        early_hits: Number of early hits

    Returns:
        Score between 0-50
    """
    if early_hits <= 0:
        return 0.0

    # Logarithmic formula: 50 * log(1 + early_hits) / log(1 + 20)
    # This gives smooth scaling with diminishing returns
    max_hits_for_cap = 20  # 20 hits = max score
    score = 50.0 * math.log1p(early_hits) / math.log1p(max_hits_for_cap)

    return min(50.0, score)


def calculate_buy_rank_score_logarithmic(avg_buy_rank: float, max_rank: int = 100) -> float:
    """
    Logarithmic scoring for buy rank (avoids arbitrary thresholds).

    Rank reflects diminishing insider advantage as rank increases.
    Rank 1 is much better than rank 10, but rank 50 vs 60 is similar.

    Rank 1 = 30 points
    Rank 10 = ~21 points
    Rank 25 = ~16 points
    Rank 50 = ~11 points
    Rank 100 = ~5 points

    Args:
        avg_buy_rank: Average buy rank across all tokens
        max_rank: Maximum rank to consider (default 100)

    Returns:
        Score between 0-30
    """
    if avg_buy_rank <= 0:
        return 30.0

    if avg_buy_rank > max_rank:
        return 0.0

    # Logarithmic decay: 30 * (1 - log(rank) / log(max_rank))
    # This gives smooth curve with no arbitrary cliffs
    log_score = 30.0 * (1.0 - math.log(avg_buy_rank) / math.log(max_rank))

    return max(0.0, min(30.0, log_score))


def calculate_whale_score(
    wallet_metrics: Dict[str, Any], patterns: List[SuspiciousPattern]
) -> float:
    """
    Calculate whale score (0-100) based on metrics and detected patterns.

    UPDATED: Uses logarithmic scaling instead of arbitrary thresholds.

    Composite score:
    - Early hit count (0-50 points): Logarithmic scaling with diminishing returns
    - Buy rank bonus (0-30 points): Logarithmic decay (rank 1 >> rank 10 >> rank 50)
    - Pattern severity sum (0-20 points): Sum of all detected pattern severities
    - Precision penalty (×0.2 to ×1.0): Applied if wallet is spray-and-pray bot

    Args:
        wallet_metrics: Dictionary with wallet metrics including:
            - early_hits: Number of successful tokens bought early
            - avg_buy_rank: Average position in buyer queue
            - score_penalty: Multiplier from activity density (0.0 to 1.0)
        patterns: List of detected SuspiciousPattern objects

    Returns:
        Whale score between 0-100
    """
    score = 0.0

    # Component 1: Early hit count (0-50 points) - LOGARITHMIC
    early_hits = wallet_metrics.get("early_hits", 0)
    early_hit_score = calculate_early_hit_score_logarithmic(early_hits)
    score += early_hit_score

    # Component 2: Buy rank bonus (0-30 points) - LOGARITHMIC
    avg_buy_rank = wallet_metrics.get("avg_buy_rank", 100)
    buy_rank_score = calculate_buy_rank_score_logarithmic(avg_buy_rank, max_rank=100)
    score += buy_rank_score

    # Component 3: Pattern severity sum (0-20 points)
    total_severity = sum(p.severity for p in patterns)
    pattern_score = min(total_severity * 4, 20)  # Each severity point = 4 score points
    score += pattern_score

    # Component 4: Apply precision penalty (CRITICAL)
    # Downgrade spray-and-pray bots that buy every token
    score_penalty = wallet_metrics.get("score_penalty", 1.0)
    score = score * score_penalty

    # Ensure score is within 0-100 range
    score = max(0, min(100, score))

    return round(score, 2)


def categorize_whale_score(score: float) -> str:
    """
    Categorize whale score into risk levels.

    Args:
        score: Whale score (0-100)

    Returns:
        Risk category string
    """
    if score >= config.WHALE_SCORE_ALERT:  # >= 80
        return "HIGH PRIORITY WHALE"
    elif score >= config.WHALE_SCORE_WATCHLIST:  # >= 60
        return "WATCHLIST"
    elif score >= 40:
        return "MODERATE INTEREST"
    elif score >= 20:
        return "LOW INTEREST"
    else:
        return "MINIMAL INTEREST"


def get_score_breakdown(
    wallet_metrics: Dict[str, Any], patterns: List[SuspiciousPattern]
) -> Dict[str, Any]:
    """
    Get detailed breakdown of whale score components.

    Args:
        wallet_metrics: Wallet metrics
        patterns: Detected patterns

    Returns:
        Dictionary with score breakdown
    """
    # Calculate individual components
    early_hits = wallet_metrics.get("early_hits", 0)
    early_hit_score = min(early_hits * 10, 50)

    avg_buy_rank = wallet_metrics.get("avg_buy_rank", 50)
    buy_rank_score = max(0, 30 * (1 - (avg_buy_rank - 1) / 49)) if avg_buy_rank > 0 else 0

    total_severity = sum(p.severity for p in patterns)
    pattern_score = min(total_severity * 4, 20)

    total_score = early_hit_score + buy_rank_score + pattern_score
    total_score = max(0, min(100, total_score))

    return {
        "total_score": round(total_score, 2),
        "category": categorize_whale_score(total_score),
        "components": {
            "early_hit_score": {
                "points": round(early_hit_score, 2),
                "max_points": 50,
                "details": f"{early_hits} early hits × 10 points each",
            },
            "buy_rank_score": {
                "points": round(buy_rank_score, 2),
                "max_points": 30,
                "details": f"Average buy rank: {avg_buy_rank:.1f}",
            },
            "pattern_score": {
                "points": round(pattern_score, 2),
                "max_points": 20,
                "details": f"{len(patterns)} patterns, total severity {total_severity}",
            },
        },
    }


def rank_wallets(
    wallet_scores: List[Dict[str, Any]], min_score: float = 0.0
) -> List[Dict[str, Any]]:
    """
    Rank wallets by score and filter by minimum threshold.

    Args:
        wallet_scores: List of dicts with 'wallet_address' and 'whale_score'
        min_score: Minimum score to include

    Returns:
        Sorted list of wallets above threshold
    """
    filtered = [w for w in wallet_scores if w.get("whale_score", 0) >= min_score]
    return sorted(filtered, key=lambda x: x.get("whale_score", 0), reverse=True)


def generate_whale_report(
    wallet_address: str,
    score: float,
    wallet_metrics: Dict[str, Any],
    patterns: List[SuspiciousPattern],
) -> str:
    """
    Generate a comprehensive whale report for a wallet.

    Args:
        wallet_address: Wallet address
        score: Whale score
        wallet_metrics: Wallet metrics
        patterns: Detected patterns

    Returns:
        Formatted report string
    """
    category = categorize_whale_score(score)
    breakdown = get_score_breakdown(wallet_metrics, patterns)

    report_lines = [
        "=" * 70,
        "WHALE ANALYSIS REPORT",
        "=" * 70,
        f"Wallet: {wallet_address}",
        f"Whale Score: {score:.2f}/100",
        f"Category: {category}",
        "",
        "SCORE BREAKDOWN:",
        f"  Early Hit Score:  {breakdown['components']['early_hit_score']['points']:.2f}/50",
        f"    → {breakdown['components']['early_hit_score']['details']}",
        f"  Buy Rank Score:   {breakdown['components']['buy_rank_score']['points']:.2f}/30",
        f"    → {breakdown['components']['buy_rank_score']['details']}",
        f"  Pattern Score:    {breakdown['components']['pattern_score']['points']:.2f}/20",
        f"    → {breakdown['components']['pattern_score']['details']}",
        "",
        "WALLET METRICS:",
        f"  Total Trades: {wallet_metrics.get('total_trades', 0)}",
        f"  Early Hits: {wallet_metrics.get('early_hits', 0)}",
        f"  Avg Buy Rank: {wallet_metrics.get('avg_buy_rank', 0):.1f}",
        f"  Same-Block Buys: {wallet_metrics.get('same_block_buys', 0)}",
        f"  Wallet Age: {wallet_metrics.get('wallet_age_days', 0)} days",
        "",
        "DETECTED PATTERNS:",
    ]

    if patterns:
        for i, pattern in enumerate(patterns, 1):
            severity_stars = "🔴" * pattern.severity
            report_lines.extend(
                [
                    f"  {i}. {pattern.name} (Severity: {pattern.severity}/5) {severity_stars}",
                    f"     {pattern.description}",
                ]
            )
    else:
        report_lines.append("  No suspicious patterns detected")

    report_lines.append("=" * 70)

    return "\n".join(report_lines)


def should_add_to_watchlist(score: float) -> bool:
    """
    Determine if wallet should be added to watchlist based on score.

    Args:
        score: Whale score

    Returns:
        True if should add to watchlist
    """
    return score >= config.WHALE_SCORE_WATCHLIST


def should_send_alert(score: float) -> bool:
    """
    Determine if wallet score warrants immediate alert.

    Args:
        score: Whale score

    Returns:
        True if should send alert
    """
    return score >= config.WHALE_SCORE_ALERT
