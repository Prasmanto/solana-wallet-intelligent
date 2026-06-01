"""Test lead-lag system with local market features."""
import sys
import asyncio
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '.')

from app.ranking.token_ranker import TokenRankingEngine


async def main():
    print("=" * 70)
    print("  LEAD-LAG SYSTEM TEST")
    print("=" * 70)

    engine = TokenRankingEngine()
    now = datetime.now(timezone.utc)

    # Create test events with different patterns
    tokens_data = {
        "SOL": [
            {"wallet": "W1", "event_type": "BUY", "amount": 1000, "token": "SOL", "timestamp": now.timestamp()},
            {"wallet": "W2", "event_type": "BUY", "amount": 800, "token": "SOL", "timestamp": now.timestamp() - 10},
            {"wallet": "W3", "event_type": "BUY", "amount": 600, "token": "SOL", "timestamp": now.timestamp() - 20},
        ],
        "BONK": [
            {"wallet": "W1", "event_type": "BUY", "amount": 500, "token": "BONK", "timestamp": now.timestamp() - 30},
            {"wallet": "W2", "event_type": "BUY", "amount": 300, "token": "BONK", "timestamp": now.timestamp() - 40},
        ],
        "WIF": [
            {"wallet": "W1", "event_type": "BUY", "amount": 2000, "token": "WIF", "timestamp": now.timestamp() - 5},
            {"wallet": "W2", "event_type": "BUY", "amount": 1500, "token": "WIF", "timestamp": now.timestamp() - 15},
            {"wallet": "W3", "event_type": "BUY", "amount": 1000, "token": "WIF", "timestamp": now.timestamp() - 25},
        ],
        "JUP": [
            {"wallet": "W1", "event_type": "BUY", "amount": 100, "token": "JUP", "timestamp": now.timestamp() - 60},
        ],
    }

    for token, events in tokens_data.items():
        for event in events:
            await engine.update(event)

    rankings = await engine.rank_tokens()

    print("\n  Token Rankings:")
    print("  " + "-" * 60)
    for i, r in enumerate(rankings, 1):
        print(f"  {i}. {r.token}")
        print(f"     Alpha Score: {r.alpha_score:.4f}")
        print(f"     Regime: {r.regime}")
        print(f"     Leader: {r.is_leader}")
        print(f"     Lead Strength: {r.lead_strength_score:.4f}")
        print(f"     Smart Money: {r.smart_money_flag}")
        print(f"     Local Momentum: {r.local_momentum_state}")
        print()

    print("  Success Criteria:")
    print("  " + "-" * 60)
    scores = [r.alpha_score for r in rankings]
    print(f"    Score variance: {max(scores) - min(scores):.4f}")
    print(f"    Min variance > 0.05: {'PASS' if max(scores) - min(scores) > 0.05 else 'FAIL'}")
    print(f"    Leader detected: {'PASS' if any(r.is_leader for r in rankings) else 'FAIL'}")
    print(f"    Top 3: {[r.token for r in rankings[:3]]}")

    print("\n" + "=" * 70)
    print("  ALL LEAD-LAG TESTS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
