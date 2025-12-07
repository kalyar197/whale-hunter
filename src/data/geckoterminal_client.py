"""
GeckoTerminal API Client

Free API for finding trending tokens and pools across 1,500+ DEXs.
No authentication required.
Rate limit: 30 calls per minute
"""

import time
import requests
from typing import List, Dict, Optional
import pandas as pd


class GeckoTerminalClient:
    """Client for GeckoTerminal API to identify successful tokens."""

    BASE_URL = "https://api.geckoterminal.com/api/v2"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def get_trending_pools(
        self,
        network: str = "eth",
        limit: int = 500,
        max_pages: int = 5,
    ) -> List[Dict]:
        """
        Get trending pools on a specific network.

        Args:
            network: Network identifier (eth, bsc, solana, base, etc.)
            limit: Max pools to return (default 500)
            max_pages: Maximum pages to fetch (default 5)

        Returns:
            List of pool data dicts
        """
        url = f"{self.BASE_URL}/networks/{network}/trending_pools"

        pools = []

        try:
            # Fetch multiple pages to get more results
            for page in range(1, max_pages + 1):
                response = self.session.get(url, params={"page": page}, timeout=10)
                response.raise_for_status()
                data = response.json()

                page_pools = data.get("data", [])
                if not page_pools:
                    break  # No more data

                for pool in page_pools:
                    attributes = pool.get("attributes", {})
                    relationships = pool.get("relationships", {})

                    # Get base token address from relationships (format: "eth_0xADDRESS")
                    base_token_data = relationships.get("base_token", {}).get("data", {})
                    token_id = base_token_data.get("id", "")

                    # Extract address from format "eth_0xADDRESS" -> "0xADDRESS"
                    if "_0x" in token_id:
                        token_address = "0x" + token_id.split("_0x")[1]
                    else:
                        continue  # Skip if no valid token address

                    # Get base token price to verify this is a valid pool
                    base_token_price = attributes.get("base_token_price_usd")
                    if not base_token_price:
                        continue

                    pools.append({
                        "pool_address": attributes.get("address", "").lower(),
                        "token_address": token_address.lower(),
                        "symbol": attributes.get("name", "").split("/")[0].strip(),
                        "name": attributes.get("name", ""),
                        "price_usd": float(attributes.get("base_token_price_usd", 0)),
                        "price_change_24h": float(attributes.get("price_change_percentage", {}).get("h24", 0)),
                        "liquidity_usd": float(attributes.get("reserve_in_usd", 0)),
                        "volume_24h": float(attributes.get("volume_usd", {}).get("h24", 0)),
                        "pool_created_at": attributes.get("pool_created_at", ""),
                        "dex": attributes.get("dex_id", ""),
                    })

                    if len(pools) >= limit:
                        return pools[:limit]

                time.sleep(0.5)  # Rate limiting between pages

            return pools[:limit]

        except Exception as e:
            print(f"Error fetching trending pools: {e}")
            return []

    def get_new_pools(
        self,
        network: str = "eth",
        limit: int = 500,
        max_pages: int = 5,
    ) -> List[Dict]:
        """
        Get newly created pools on a specific network.

        Args:
            network: Network identifier
            limit: Max pools to return (default 500)
            max_pages: Maximum pages to fetch (default 5)

        Returns:
            List of pool data dicts
        """
        url = f"{self.BASE_URL}/networks/{network}/new_pools"

        pools = []

        try:
            for page in range(1, max_pages + 1):
                response = self.session.get(url, params={"page": page}, timeout=10)
                response.raise_for_status()
                data = response.json()

                page_pools = data.get("data", [])
                if not page_pools:
                    break

                for pool in page_pools:
                    attributes = pool.get("attributes", {})
                    relationships = pool.get("relationships", {})

                    # Get base token address from relationships (format: "eth_0xADDRESS")
                    base_token_data = relationships.get("base_token", {}).get("data", {})
                    token_id = base_token_data.get("id", "")

                    # Extract address from format "eth_0xADDRESS" -> "0xADDRESS"
                    if "_0x" in token_id:
                        token_address = "0x" + token_id.split("_0x")[1]
                    else:
                        continue  # Skip if no valid token address

                    pools.append({
                        "pool_address": attributes.get("address", "").lower(),
                        "token_address": token_address.lower(),
                        "symbol": attributes.get("name", "").split("/")[0].strip(),
                        "name": attributes.get("name", ""),
                        "price_usd": float(attributes.get("base_token_price_usd", 0)),
                        "price_change_24h": float(attributes.get("price_change_percentage", {}).get("h24", 0)),
                        "liquidity_usd": float(attributes.get("reserve_in_usd", 0)),
                        "volume_24h": float(attributes.get("volume_usd", {}).get("h24", 0)),
                        "pool_created_at": attributes.get("pool_created_at", ""),
                        "dex": attributes.get("dex_id", ""),
                    })

                    if len(pools) >= limit:
                        return pools[:limit]

                time.sleep(0.5)  # Rate limiting between pages

            return pools[:limit]

        except Exception as e:
            print(f"Error fetching new pools: {e}")
            return []

    def find_4x_tokens(
        self,
        network: str = "eth",
        min_return_multiple: float = 2.5,
        batch_delay: float = 2.0,
    ) -> pd.DataFrame:
        """
        Find tokens that achieved high returns using trending and new pools.

        Strategy:
        1. Get trending pools (high activity) - multiple pages
        2. Get new pools (recent launches) - multiple pages
        3. Filter for tokens with significant gains

        Args:
            network: Network to search (eth, bsc, solana, etc.)
            min_return_multiple: Minimum return (2.5 = 2.5x = 150% gain)
            batch_delay: Delay between API calls (rate limiting)

        Returns:
            DataFrame with successful token addresses
        """
        print(f"Searching for {min_return_multiple}x+ tokens on {network}...")
        print()
        print("Using GeckoTerminal API (FREE, 30 calls/min)")
        print("Fetching multiple pages of trending + new pools for more results...")
        print()

        successful_tokens = []
        min_price_change = (min_return_multiple - 1) * 100  # 2.5x = 150% gain

        # Get trending pools (multiple pages)
        print("  Fetching trending pools (up to 500 pools across 5 pages)...")
        trending_pools = self.get_trending_pools(network=network, limit=500, max_pages=5)
        print(f"    Found {len(trending_pools)} trending pools")

        time.sleep(batch_delay)  # Rate limiting

        # Get new pools (multiple pages)
        print("  Fetching new pools (up to 500 pools across 5 pages)...")
        new_pools = self.get_new_pools(network=network, limit=500, max_pages=5)
        print(f"    Found {len(new_pools)} new pools")

        # Combine and deduplicate
        all_pools = trending_pools + new_pools
        seen_tokens = set()

        for pool in all_pools:
            token_address = pool["token_address"]
            price_change_24h = pool["price_change_24h"]

            # Skip if already processed
            if token_address in seen_tokens:
                continue

            # Filter for 4x+ gainers
            if price_change_24h >= min_price_change:
                seen_tokens.add(token_address)
                successful_tokens.append({
                    "token_address": token_address,
                    "symbol": pool["symbol"],
                    "name": pool["name"],
                    "price_change_24h": price_change_24h,
                    "liquidity_usd": pool["liquidity_usd"],
                    "volume_24h": pool["volume_24h"],
                    "pair_created_at": pool["pool_created_at"],
                    "estimated_return": (price_change_24h / 100) + 1,
                })

        print()
        print(f"Found {len(successful_tokens)} tokens with {min_return_multiple}x+ gains")

        if len(successful_tokens) == 0:
            print()
            print("WARNING: No 4x+ tokens found right now")
            print("This is normal - not all days have major pumps")
            print("You can:")
            print("  1. Try again later")
            print("  2. Lower the threshold (e.g., 2x instead of 4x)")
            print("  3. Manually add token addresses to data/exports/successful_tokens.csv")

        return pd.DataFrame(successful_tokens)


def get_successful_token_list(
    network: str = "eth",
    min_return: float = 4.0,
    output_file: Optional[str] = None,
) -> List[str]:
    """
    Convenience function to get a simple list of 4x+ token addresses.

    Args:
        network: Network to search
        min_return: Minimum return multiple (4.0 = 4x)
        output_file: Optional CSV file to save results

    Returns:
        List of token addresses
    """
    client = GeckoTerminalClient()

    df = client.find_4x_tokens(network=network, min_return_multiple=min_return)

    if output_file and not df.empty:
        df.to_csv(output_file, index=False)
        print(f"Saved {len(df)} tokens to {output_file}")

    return df["token_address"].tolist() if not df.empty else []
