import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent


@dataclass
class Config:
    """Configuration settings for Whale Hunter"""

    # API Keys (load from environment)
    BIGQUERY_PROJECT: str = os.getenv("BIGQUERY_PROJECT", "")
    GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv(
        "GOOGLE_APPLICATION_CREDENTIALS", ""
    )
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Detection Thresholds
    MIN_EARLY_HITS: int = 5  # Minimum number of early hits to be considered
    FIRST_N_BUYERS: int = 100  # Consider first N buyers as "early" (expanded from 50 to catch stealth insiders)
    MIN_TOKEN_RETURN_MULTIPLE: float = 10.0  # Token must achieve 10x return
    LOOKBACK_DAYS: int = 180  # Analyze last 6 months of data
    MIN_WHALE_BUY_ETH: float = 0.1  # Minimum ETH buy value to filter out small buyers and spray-and-pray bots

    # Pattern Detection Thresholds
    LIQUIDITY_SNIPER_MIN_HITS: int = 3  # Min same-block buys to flag as sniper
    FRESH_WALLET_DAYS: int = 7  # New wallet threshold in days
    CLUSTER_MIN_SIZE: int = 5  # Min wallets in cluster to flag
    EARLY_BUYER_AVG_RANK_THRESHOLD: int = 20  # Avg buy rank for consistent early buyer
    STRATEGIC_DUMPER_MIN_EXITS: int = 3  # Min strategic exits (sold >50%) to flag as dumper

    # Whale Score Thresholds
    WHALE_SCORE_WATCHLIST: float = 60.0  # Add to watchlist if score >= this
    WHALE_SCORE_ALERT: float = 80.0  # High-priority whale

    # BigQuery Settings
    BIGQUERY_MAX_BYTES_BILLED: int = 10 * 1024**3  # 10 GB limit
    BIGQUERY_COST_PER_TB: float = 5.0  # $5 per TB scanned
    BIGQUERY_WARN_THRESHOLD_GB: float = 10.0  # Warn if query scans >10 GB

    # Storage Paths
    DB_PATH: str = str(PROJECT_ROOT / "data" / "whales.db")
    EXPORTS_DIR: str = str(PROJECT_ROOT / "data" / "exports")
    QUERIES_DIR: str = str(PROJECT_ROOT / "queries" / "ethereum")

    # Output Settings
    MAX_RESULTS_DISPLAY: int = 50  # Max results to show in reports

    def validate(self) -> tuple[bool, list[str]]:
        """
        Validate configuration settings.

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []

        if not self.BIGQUERY_PROJECT:
            errors.append("BIGQUERY_PROJECT not set in environment")

        if not self.GOOGLE_APPLICATION_CREDENTIALS:
            errors.append("GOOGLE_APPLICATION_CREDENTIALS not set in environment")
        elif not os.path.exists(self.GOOGLE_APPLICATION_CREDENTIALS):
            errors.append(
                f"Service account file not found: {self.GOOGLE_APPLICATION_CREDENTIALS}"
            )

        return len(errors) == 0, errors


# Global config instance
config = Config()
