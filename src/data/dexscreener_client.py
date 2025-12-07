"""
DEXScreener API Client

Fetches token performance data to identify actual 10x+ tokens.
This solves the critical gap: BigQuery can't tell us which tokens are profitable.

Free API with no authentication required.
Rate limit: ~300 requests/minute
"""

import time
import requests
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import pandas as pd


class DEXScreenerClient:
    """Client for DEXScreener API to identify successful tokens."""

    BASE_URL = "https://api.dexscreener.com/latest"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def search_pairs(
        self,
        query: str = "",
        min_liquidity_usd: float = 50000,
        min_volume_24h: float = 10000,
        limit: int = 100,
    ) -> List[Dict]:
        """
        Search for trading pairs.
        NOTE: DEXScreener free API has limited search capabilities.
        This method uses the search endpoint which may have rate limits.

        Args:
            query: Search query (token symbol/address)
            min_liquidity_usd: Minimum liquidity to filter scams
            min_volume_24h: Minimum 24h volume
            limit: Max tokens to return

        Returns:
            List of token data dicts
        """
        # DEXScreener search endpoint
        url = f"{self.BASE_URL}/dex/search/?q={query}"

        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            tokens = []
            for pair in data.get("pairs", []):
                # Filter by liquidity and volume
                liquidity = float(pair.get("liquidity", {}).get("usd", 0))
                volume_24h = float(pair.get("volume", {}).get("h24", 0))

                if liquidity >= min_liquidity_usd and volume_24h >= min_volume_24h:
                    tokens.append(
                        {
                            "token_address": pair.get("baseToken", {}).get("address", "").lower(),
                            "symbol": pair.get("baseToken", {}).get("symbol", ""),
                            "name": pair.get("baseToken", {}).get("name", ""),
                            "price_usd": float(pair.get("priceUsd", 0)),
                            "price_change_24h": float(pair.get("priceChange", {}).get("h24", 0)),
                            "liquidity_usd": liquidity,
                            "volume_24h": volume_24h,
                            "pair_created_at": pair.get("pairCreatedAt", 0),
                        }
                    )

                if len(tokens) >= limit:
                    break

            return tokens

        except Exception as e:
            print(f"Error searching pairs: {e}")
            return []

    def get_token_info(self, token_address: str, chain: str = "ethereum") -> Optional[Dict]:
        """
        Get detailed info for a specific token.

        Args:
            token_address: Token contract address
            chain: Blockchain name

        Returns:
            Token info dict or None if not found
        """
        url = f"{self.BASE_URL}/dex/tokens/{token_address}"

        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            pairs = data.get("pairs", [])
            if not pairs:
                return None

            # Use the pair with highest liquidity
            main_pair = max(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0)))

            return {
                "token_address": token_address.lower(),
                "symbol": main_pair.get("baseToken", {}).get("symbol", ""),
                "name": main_pair.get("baseToken", {}).get("name", ""),
                "price_usd": float(main_pair.get("priceUsd", 0)),
                "price_change_5m": float(main_pair.get("priceChange", {}).get("m5", 0)),
                "price_change_1h": float(main_pair.get("priceChange", {}).get("h1", 0)),
                "price_change_6h": float(main_pair.get("priceChange", {}).get("h6", 0)),
                "price_change_24h": float(main_pair.get("priceChange", {}).get("h24", 0)),
                "liquidity_usd": float(main_pair.get("liquidity", {}).get("usd", 0)),
                "volume_24h": float(main_pair.get("volume", {}).get("h24", 0)),
                "pair_created_at": main_pair.get("pairCreatedAt", 0),
                "dex": main_pair.get("dexId", ""),
            }

        except Exception as e:
            print(f"Error fetching token {token_address}: {e}")
            return None

    def find_10x_tokens(
        self,
        chain: str = "ethereum",
        days_back: int = 180,
        min_return_multiple: float = 4.0,
        batch_delay: float = 0.3,
    ) -> pd.DataFrame:
        """
        Find tokens that achieved 4x+ returns in the specified timeframe.

        Strategy:
        1. Search for tokens using DEXScreener API
        2. Check their price changes
        3. Filter for tokens that did >=4x (300%+ gain)

        Args:
            chain: Blockchain to search
            days_back: Look back period in days
            min_return_multiple: Minimum return (4.0 = 4x)
            batch_delay: Delay between API calls (rate limiting)

        Returns:
            DataFrame with successful token addresses
        """
        print(f"Searching for {min_return_multiple}x tokens on {chain}...")
        print()
        print("NOTE: Using DEXScreener search API with broad queries.")
        print("This will find recently pumped tokens on Ethereum.")
        print()

        successful_tokens = []
        search_queries = ["PEPE", "SHIB", "DOGE", "WOJAK", "MEME", "AI", "TRUMP", "FROG", "CAT", "DOG"]

        for query in search_queries:
            print(f"  Searching for '{query}' tokens...")
            try:
                pairs = self.search_pairs(query=query, min_liquidity_usd=10000, min_volume_24h=5000, limit=20)

                for token in pairs:
                    price_change_24h = token.get("price_change_24h", 0)

                    # Filter for 4x+ gainers (300%+ = 4x gain)
                    if price_change_24h >= 300:
                        # Check if we already have this token
                        if not any(t["token_address"] == token["token_address"] for t in successful_tokens):
                            successful_tokens.append({
                                "token_address": token["token_address"],
                                "symbol": token["symbol"],
                                "name": token["name"],
                                "price_change_24h": price_change_24h,
                                "liquidity_usd": token["liquidity_usd"],
                                "volume_24h": token["volume_24h"],
                                "pair_created_at": token["pair_created_at"],
                                "estimated_return": price_change_24h / 100,
                            })

                time.sleep(batch_delay)  # Rate limiting

            except Exception as e:
                print(f"    Error searching '{query}': {e}")
                continue

        print(f"\nFound {len(successful_tokens)} potential 4x+ tokens")

        if len(successful_tokens) == 0:
            print("\nWARNING: No tokens found!")
            print("You can manually add token addresses to data/successful_tokens.csv")
            print("Format: token_address,symbol,name,price_change_24h,liquidity_usd,volume_24h,pair_created_at,estimated_return")

        return pd.DataFrame(successful_tokens)

    def find_sustained_10x_tokens(
        self,
        chain: str = "ethereum",
        min_liquidity_usd: float = 50000,
        min_volume_24h: float = 10000,
        batch_delay: float = 0.3,
    ) -> pd.DataFrame:
        """
        Find tokens with SUSTAINED 10x gains across multiple timeframes (Option A).

        CRITICAL: This solves the 24h snapshot problem by requiring tokens to
        maintain gains across 1h, 6h, AND 24h timeframes. Filters out pump-and-dumps.

        Multi-Timeframe Requirements (diminishing for longer periods):
        - 1h: >= 1000% (10x) - Strong recent momentum
        - 6h: >= 800% (8x) - Sustained over hours
        - 24h: >= 500% (5x) - Proven stability

        Strategy:
        1. Get top gainers from DEXScreener
        2. For each token, fetch detailed info with multi-timeframe price data
        3. Only include tokens that meet ALL three timeframe thresholds
        4. Return intersection of tokens that sustained gains

        Args:
            chain: Blockchain to search (ethereum, base, etc.)
            min_liquidity_usd: Minimum liquidity to filter scams
            min_volume_24h: Minimum 24h volume
            batch_delay: Delay between API calls for rate limiting

        Returns:
            DataFrame with sustained 10x tokens and all timeframe data
        """
        print(f"Searching for SUSTAINED 10x tokens on {chain} (multi-timeframe verification)...")
        print("Thresholds: 1h >= 1000%, 6h >= 800%, 24h >= 500%")

        # Get top gainers
        print("Fetching top gainers...")
        top_tokens = self.get_top_gainers(
            chain=chain,
            min_liquidity_usd=min_liquidity_usd,
            min_volume_24h=min_volume_24h,
            limit=100
        )

        sustained_tokens = []

        for i, token in enumerate(top_tokens):
            token_address = token["token_address"]

            # Fetch detailed info with multi-timeframe price changes
            token_info = self.get_token_info(token_address, chain=chain)

            if not token_info:
                continue

            # Extract price changes across all timeframes
            price_1h = token_info.get("price_change_1h", 0)
            price_6h = token_info.get("price_change_6h", 0)
            price_24h = token_info.get("price_change_24h", 0)

            # CRITICAL: Check if token sustained gains across ALL timeframes
            # This filters out pump-and-dumps that spike and crash
            sustained = (
                price_1h >= 1000  # 10x in 1h
                and price_6h >= 800  # 8x in 6h
                and price_24h >= 500  # 5x in 24h
            )

            if sustained:
                sustained_tokens.append(
                    {
                        "token_address": token_address,
                        "symbol": token_info["symbol"],
                        "name": token_info["name"],
                        "price_usd": token_info["price_usd"],
                        "price_change_1h": price_1h,
                        "price_change_6h": price_6h,
                        "price_change_24h": price_24h,
                        "liquidity_usd": token_info["liquidity_usd"],
                        "volume_24h": token_info["volume_24h"],
                        "pair_created_at": token_info["pair_created_at"],
                        "dex": token_info["dex"],
                        "verification_status": "sustained_10x",
                    }
                )

            # Rate limiting
            if (i + 1) % 10 == 0:
                print(f"  Processed {i+1}/{len(top_tokens)} tokens... (found {len(sustained_tokens)} sustained)")
                time.sleep(batch_delay)

        print(f"\n✅ Found {len(sustained_tokens)} tokens with SUSTAINED 10x gains across all timeframes")
        print(f"   (Filtered out {len(top_tokens) - len(sustained_tokens)} pump-and-dumps)")

        return pd.DataFrame(sustained_tokens)

    def get_tokens_by_age(
        self,
        chain: str = "ethereum",
        min_age_days: int = 1,
        max_age_days: int = 180,
        limit: int = 500,
    ) -> List[str]:
        """
        Get token addresses within a specific age range.

        Args:
            chain: Blockchain
            min_age_days: Minimum token age
            max_age_days: Maximum token age
            limit: Max tokens to return

        Returns:
            List of token addresses
        """
        # DEXScreener doesn't have a direct "by age" endpoint
        # We approximate by getting trending tokens and filtering by pairCreatedAt

        now = int(time.time())
        min_timestamp = now - (max_age_days * 86400)
        max_timestamp = now - (min_age_days * 86400)

        tokens = self.get_top_gainers(chain=chain, limit=limit)

        filtered = [
            token["token_address"]
            for token in tokens
            if min_timestamp <= token.get("pair_created_at", 0) <= max_timestamp
        ]

        return filtered


def get_successful_token_list(
    chain: str = "ethereum",
    min_return: float = 10.0,
    output_file: Optional[str] = None,
    use_multi_timeframe: bool = True,
) -> List[str]:
    """
    Convenience function to get a simple list of 10x+ token addresses.

    UPDATED: Now uses multi-timeframe verification by default to filter pump-and-dumps.

    Args:
        chain: Blockchain to search
        min_return: Minimum return multiple (not used with multi_timeframe)
        output_file: Optional CSV file to save results
        use_multi_timeframe: Use sustained gains verification (recommended)

    Returns:
        List of token addresses
    """
    client = DEXScreenerClient()

    if use_multi_timeframe:
        # RECOMMENDED: Multi-timeframe verification (Option A)
        # Filters out pump-and-dumps that don't sustain gains
        df = client.find_sustained_10x_tokens(chain=chain)
    else:
        # Legacy method: Simple 24h snapshot
        df = client.find_10x_tokens(chain=chain, min_return_multiple=min_return)

    if output_file and not df.empty:
        df.to_csv(output_file, index=False)
        print(f"Saved {len(df)} tokens to {output_file}")

    return df["token_address"].tolist() if not df.empty else []
