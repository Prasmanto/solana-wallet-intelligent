"""Price feed test script.

Tests Jupiter Price API V3 connectivity and price availability.
Run locally or on VPS to verify price feed health.

Usage:
    python scripts/test_price_feed.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config.settings import settings


async def test_price_feed() -> None:
    """Test Jupiter Price API V3."""
    import httpx

    url = settings.JUPITER_PRICE_BASE_URL

    # Known mints
    USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    SOL_MINT = "So11111111111111111111111111111111111111112"
    FAKE_MINT = "FakeToken1111111111111111111111111111111111111"

    # Get a recent candidate token from DB (if available)
    candidate_mint = None
    try:
        from app.infrastructure.database.session import async_session_factory
        from sqlalchemy import text

        async with async_session_factory() as session:
            stmt = text("""
                SELECT token_mint FROM token_rankings
                WHERE rank > 0 AND rank <= 20
                ORDER BY created_at DESC LIMIT 1
            """)
            result = await session.execute(stmt)
            row = result.fetchone()
            if row:
                candidate_mint = row[0]
    except Exception:
        pass

    print("\n" + "=" * 60)
    print("  JUPITER PRICE API V3 TEST")
    print("=" * 60)
    print(f"\n  Endpoint: {url}")

    # Test tokens
    test_tokens = [
        ("USDC", USDC_MINT),
        ("SOL", SOL_MINT),
        ("Fake/Unknown", FAKE_MINT),
    ]
    if candidate_mint:
        test_tokens.insert(2, ("Candidate", candidate_mint))

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Test 1: Single token
        print("\n  --- Single Token Tests ---")
        for label, mint in test_tokens:
            try:
                resp = await client.get(url, params={"ids": mint})
                resp.raise_for_status()
                data = resp.json()

                if mint in data and isinstance(data[mint], dict):
                    price = data[mint].get("usdPrice")
                    decimals = data[mint].get("decimals")
                    liquidity = data[mint].get("liquidity")
                    print(f"  {label:20s}  price=${price:.6f}  decimals={decimals}  liquidity={liquidity:.0f}")
                else:
                    print(f"  {label:20s}  NO PRICE (not in response)")
            except httpx.TimeoutException:
                print(f"  {label:20s}  TIMEOUT")
            except httpx.HTTPStatusError as e:
                print(f"  {label:20s}  HTTP {e.response.status_code}")
            except Exception as e:
                print(f"  {label:20s}  ERROR: {e}")

        # Test 2: Batch request
        print("\n  --- Batch Request Test ---")
        all_mints = [mint for _, mint in test_tokens]
        ids_param = ",".join(all_mints)
        try:
            resp = await client.get(url, params={"ids": ids_param})
            resp.raise_for_status()
            data = resp.json()

            found = sum(1 for m in all_mints if m in data)
            print(f"  Requested: {len(all_mints)} tokens")
            print(f"  Found:     {found} tokens")
            for label, mint in test_tokens:
                if mint in data and isinstance(data[mint], dict):
                    price = data[mint].get("usdPrice")
                    print(f"    {label:20s}  ${price:.6f}")
                else:
                    print(f"    {label:20s}  (no price)")
        except Exception as e:
            print(f"  Batch error: {e}")

        # Test 3: Latency
        print("\n  --- Latency Test ---")
        import time
        latencies = []
        for i in range(3):
            start = time.time()
            try:
                resp = await client.get(url, params={"ids": SOL_MINT})
                resp.raise_for_status()
                latency = (time.time() - start) * 1000
                latencies.append(latency)
                print(f"  Request {i+1}: {latency:.0f}ms")
            except Exception as e:
                print(f"  Request {i+1}: ERROR - {e}")

        if latencies:
            avg = sum(latencies) / len(latencies)
            print(f"  Average: {avg:.0f}ms")

    print("\n" + "=" * 60)
    print("  TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_price_feed())
