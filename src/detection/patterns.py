from dataclasses import dataclass
from typing import List, Dict, Any
from config.settings import config


@dataclass
class SuspiciousPattern:
    """Represents a detected suspicious pattern."""

    name: str
    severity: int  # 1-5, where 5 is most severe
    description: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "severity": self.severity,
            "description": self.description,
        }


def detect_patterns(wallet_metrics: Dict[str, Any]) -> List[SuspiciousPattern]:
    """
    Detect suspicious patterns that indicate insider knowledge.

    NO win rate analysis - we only care about pattern matching.

    Args:
        wallet_metrics: Dictionary containing:
            - early_hits: Number of successful tokens bought early
            - avg_buy_rank: Average position in buyer queue
            - same_block_buys: Count of same-block buys
            - wallet_age_days: Days since wallet created
            - cluster_size: Number of wallets in connected cluster (optional)
            - total_trades: Total number of trades

    Returns:
        List of detected suspicious patterns
    """
    patterns = []

    # Pattern 1: CONSISTENT_EARLY_BUYER
    # Avg buy rank <=20, 5+ early hits on pumped tokens
    if (
        wallet_metrics.get("early_hits", 0) >= config.MIN_EARLY_HITS
        and wallet_metrics.get("avg_buy_rank", 999) <= config.EARLY_BUYER_AVG_RANK_THRESHOLD
    ):
        patterns.append(
            SuspiciousPattern(
                name="CONSISTENT_EARLY_BUYER",
                severity=5,
                description=(
                    f"Consistently bought early (avg rank {wallet_metrics['avg_buy_rank']:.0f}) "
                    f"on {wallet_metrics['early_hits']} successful tokens"
                ),
            )
        )

    # Pattern 2: LIQUIDITY_SNIPER (Context-Aware)
    # 3+ same-block buys (bought in same block as liquidity add)
    # CRITICAL: Context matters! Fresh wallet sniping = insider. Old bot sniping = MEV noise.
    if wallet_metrics.get("same_block_buys", 0) >= config.LIQUIDITY_SNIPER_MIN_HITS:
        wallet_age_days = wallet_metrics.get("wallet_age_days", 999)
        same_block_count = wallet_metrics.get("same_block_buys", 0)

        # Fresh wallet + sniping = likely insider (HIGH severity)
        if wallet_age_days < config.FRESH_WALLET_DAYS:
            severity = 5
            description = (
                f"INSIDER SIGNAL: Fresh wallet ({wallet_age_days}d old) sniping liquidity adds "
                f"({same_block_count} times) - likely has advance knowledge"
            )
        # Old wallet + sniping = generic MEV bot (LOW severity)
        else:
            severity = 2
            description = (
                f"MEV bot behavior: routine sniping ({same_block_count} same-block buys) "
                f"on established wallet ({wallet_age_days}d old)"
            )

        patterns.append(
            SuspiciousPattern(
                name="LIQUIDITY_SNIPER",
                severity=severity,
                description=description,
            )
        )

    # Pattern 3: FRESH_WALLET_ALPHA
    # New wallet (<7 days) that immediately starts sniping
    if (
        wallet_metrics.get("wallet_age_days", 999) <= config.FRESH_WALLET_DAYS
        and wallet_metrics.get("early_hits", 0) >= 2  # At least 2 early hits on fresh wallet
    ):
        patterns.append(
            SuspiciousPattern(
                name="FRESH_WALLET_ALPHA",
                severity=4,
                description=(
                    f"Fresh wallet ({wallet_metrics['wallet_age_days']} days old) "
                    f"immediately started early buying with {wallet_metrics['early_hits']} hits"
                ),
            )
        )

    # Pattern 4: WALLET_CLUSTER
    # Part of 5+ wallet cluster with common funding source
    if wallet_metrics.get("cluster_size", 1) >= config.CLUSTER_MIN_SIZE:
        patterns.append(
            SuspiciousPattern(
                name="WALLET_CLUSTER",
                severity=4,
                description=(
                    f"Part of {wallet_metrics['cluster_size']}-wallet cluster, "
                    "indicating potential Sybil attack (one entity, multiple wallets)"
                ),
            )
        )

    # Pattern 5: STRATEGIC_DUMPER (NEW)
    # Wallet that buys early and sells (exits) - true predator behavior
    # This distinguishes insiders/traders from lucky holders
    strategic_exit_count = wallet_metrics.get("strategic_exit_count", 0)
    avg_hold_time_hours = wallet_metrics.get("avg_hold_time_hours", 999999)

    if strategic_exit_count >= config.STRATEGIC_DUMPER_MIN_EXITS:
        # Quick flip (< 48 hours) = likely insider
        if avg_hold_time_hours < 48:
            severity = 5
            description = (
                f"PREDATOR ALERT: Strategic dumper with {strategic_exit_count} exits "
                f"(avg hold time: {avg_hold_time_hours:.1f}h) - likely insider flipping tokens"
            )
        # Slower exit but still exiting = trader/profit taker
        else:
            severity = 4
            description = (
                f"Profit taker: {strategic_exit_count} strategic exits "
                f"(avg hold time: {avg_hold_time_hours:.1f}h) - trader behavior"
            )

        patterns.append(
            SuspiciousPattern(
                name="STRATEGIC_DUMPER",
                severity=severity,
                description=description,
            )
        )

    return patterns


def get_pattern_summary(patterns: List[SuspiciousPattern]) -> Dict[str, Any]:
    """
    Get summary statistics about detected patterns.

    Args:
        patterns: List of detected patterns

    Returns:
        Dictionary with summary stats
    """
    if not patterns:
        return {
            "total_patterns": 0,
            "total_severity": 0,
            "pattern_names": [],
            "max_severity": 0,
        }

    return {
        "total_patterns": len(patterns),
        "total_severity": sum(p.severity for p in patterns),
        "pattern_names": [p.name for p in patterns],
        "max_severity": max(p.severity for p in patterns),
        "patterns": [p.to_dict() for p in patterns],
    }


def generate_pattern_report(
    wallet_address: str, patterns: List[SuspiciousPattern]
) -> str:
    """
    Generate a human-readable report of detected patterns.

    Args:
        wallet_address: Wallet address
        patterns: List of detected patterns

    Returns:
        Formatted report string
    """
    if not patterns:
        return f"Wallet {wallet_address[:16]}... : No suspicious patterns detected"

    report_lines = [
        f"=" * 70,
        f"SUSPICIOUS PATTERN REPORT",
        f"Wallet: {wallet_address}",
        f"Total Patterns: {len(patterns)}",
        f"Total Severity: {sum(p.severity for p in patterns)}",
        f"=" * 70,
        "",
    ]

    for i, pattern in enumerate(patterns, 1):
        severity_stars = "🔴" * pattern.severity
        report_lines.extend(
            [
                f"{i}. {pattern.name} {severity_stars}",
                f"   Severity: {pattern.severity}/5",
                f"   {pattern.description}",
                "",
            ]
        )

    report_lines.append("=" * 70)

    return "\n".join(report_lines)


def filter_patterns_by_severity(
    patterns: List[SuspiciousPattern], min_severity: int = 4
) -> List[SuspiciousPattern]:
    """
    Filter patterns by minimum severity level.

    Args:
        patterns: List of patterns
        min_severity: Minimum severity to include

    Returns:
        Filtered list of patterns
    """
    return [p for p in patterns if p.severity >= min_severity]


def check_if_likely_insider(patterns: List[SuspiciousPattern]) -> bool:
    """
    Determine if pattern combination indicates likely insider trading.

    Args:
        patterns: List of detected patterns

    Returns:
        True if likely insider, False otherwise
    """
    if not patterns:
        return False

    pattern_names = {p.name for p in patterns}
    total_severity = sum(p.severity for p in patterns)

    # Strong insider indicators
    if "CONSISTENT_EARLY_BUYER" in pattern_names and "LIQUIDITY_SNIPER" in pattern_names:
        return True

    if total_severity >= 15:  # Very high total severity
        return True

    if len(patterns) >= 4:  # Many different patterns
        return True

    return False
