"""
Wallet Analyzer Script

This script analyzes candidate wallets and calculates whale scores.

Usage:
    python scripts/02_analyze_wallets.py

Steps:
1. Load candidate wallets from DuckDB
2. For each wallet:
   - Calculate basic metrics
   - Analyze early buying patterns
   - Detect suspicious patterns
   - Calculate whale score
3. Update database with scores
4. Add high scorers to watchlist
5. Generate report
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import duckdb
import pandas as pd
from config.settings import config
from src.data.storage import (
    get_wallet_trades,
    update_whale_score,
    add_to_watchlist,
    insert_pattern,
    get_top_whales,
)
from src.analysis.wallet_metrics import calculate_wallet_metrics
from src.analysis.early_buyer import analyze_early_buying_pattern
from src.detection.patterns import detect_patterns
from src.detection.scorer import (
    calculate_whale_score,
    generate_whale_report,
    should_add_to_watchlist,
)


def main():
    print("=" * 70)
    print("WHALE HUNTER - WALLET ANALYZER")
    print("=" * 70)
    print()

    # Connect to database
    db_path = config.DB_PATH
    if not Path(db_path).exists():
        print(f"❌ Database not found: {db_path}")
        print("Please run scripts/01_fetch_historical.py first")
        return

    print(f"Connecting to database: {db_path}")
    con = duckdb.connect(db_path)

    # Get all wallets that need analysis
    print("Loading candidate wallets...")
    wallets_df = con.execute(
        """
        SELECT address, chain
        FROM wallets
        WHERE whale_score IS NULL OR updated_at < CURRENT_TIMESTAMP - INTERVAL '1 day'
    """
    ).fetchdf()

    if len(wallets_df) == 0:
        print("No wallets to analyze. All wallets are up to date.")
        con.close()
        return

    print(f"Found {len(wallets_df)} wallets to analyze")
    print()

    # Analyze each wallet
    results = []
    for i, row in wallets_df.iterrows():
        wallet = row["address"]
        chain = row["chain"]

        print(f"[{i+1}/{len(wallets_df)}] Analyzing {wallet[:16]}...")

        # Get wallet trades
        trades_df = get_wallet_trades(con, wallet)

        if trades_df.empty:
            print(f"  ⚠️  No trades found, skipping...")
            continue

        # Calculate basic metrics
        basic_metrics = calculate_wallet_metrics(trades_df)

        # Analyze early buying patterns
        early_buyer_metrics = analyze_early_buying_pattern(trades_df)

        # Combine all metrics
        combined_metrics = {**basic_metrics, **early_buyer_metrics}

        # Detect patterns
        patterns = detect_patterns(combined_metrics)

        # Calculate whale score
        score = calculate_whale_score(combined_metrics, patterns)

        print(f"  Whale Score: {score:.2f}/100")
        print(f"  Early Hits: {combined_metrics['early_hits']}")
        print(f"  Avg Buy Rank: {combined_metrics['avg_buy_rank']:.1f}")
        print(f"  Patterns: {len(patterns)}")

        # Update database
        update_whale_score(
            con,
            wallet,
            score,
            combined_metrics["early_hits"],
            combined_metrics["avg_buy_rank"],
        )

        # Insert detected patterns
        for pattern in patterns:
            insert_pattern(con, wallet, pattern.name, pattern.severity, pattern.description)

        # Add to watchlist if score is high enough
        if should_add_to_watchlist(score):
            add_to_watchlist(
                con,
                wallet,
                chain,
                score,
                notes=f"{len(patterns)} patterns detected",
            )
            print(f"  ✓ Added to watchlist")

        # Store result for report
        results.append(
            {
                "wallet": wallet,
                "score": score,
                "metrics": combined_metrics,
                "patterns": patterns,
            }
        )

        print()

    # Generate summary report
    print("=" * 70)
    print("ANALYSIS COMPLETE - SUMMARY")
    print("=" * 70)
    print()

    # Get top whales from database
    top_whales = get_top_whales(con, limit=20)

    print(f"Top {len(top_whales)} Whale Wallets:\n")
    print(f"{'Rank':<6} {'Wallet':<18} {'Score':<8} {'Early Hits':<12} {'Avg Rank':<10} {'Patterns'}")
    print("-" * 70)

    for i, whale in top_whales.iterrows():
        wallet_short = whale["address"][:16] + "..."
        patterns_str = ", ".join(whale["patterns"]) if whale["patterns"] else "None"
        print(
            f"{i+1:<6} {wallet_short:<18} {whale['whale_score']:<8.2f} "
            f"{whale['early_hit_count']:<12} {whale['avg_buy_rank']:<10.1f} {patterns_str}"
        )

    print()

    # Save detailed report to file
    report_path = project_root / "data" / "whale_report.csv"
    top_whales.to_csv(report_path, index=False)
    print(f"✓ Detailed report saved to: {report_path}")

    # Print detailed report for top 3 whales
    print()
    print("=" * 70)
    print("DETAILED REPORTS - TOP 3 WHALES")
    print("=" * 70)
    print()

    for result in sorted(results, key=lambda x: x["score"], reverse=True)[:3]:
        report = generate_whale_report(
            result["wallet"],
            result["score"],
            result["metrics"],
            result["patterns"],
        )
        print(report)
        print()

    # Database statistics
    print("=" * 70)
    print("DATABASE STATISTICS")
    print("=" * 70)

    watchlist_count = con.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    high_priority_count = con.execute(
        f"SELECT COUNT(*) FROM wallets WHERE whale_score >= {config.WHALE_SCORE_ALERT}"
    ).fetchone()[0]

    print(f"Total Wallets: {len(wallets_df)}")
    print(f"Watchlist Size: {watchlist_count}")
    print(f"High Priority (>=80): {high_priority_count}")
    print()

    print("✓ Wallet analysis completed!")
    print("=" * 70)

    # Close connection
    con.close()


if __name__ == "__main__":
    main()
