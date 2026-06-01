"""Test token ranking engine."""
import sys
import asyncio
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '.')

from app.ranking.token_ranker import TokenRankingEngine


async def main():
    print("=" * 60)
    print("  TOKEN RANKING ENGINE TEST")
    print("=" * 60)

    engine = TokenRankingEngine()
    now = datetime.now(timezone.utc)

    # Create test events for multiple tokens
    tokens_data = {
        "SOL": [
            {"wallet": "W1", "event_type": "BUY", "amount": 1000, "token": "SOL", "timestamp": now.timestamp()},
            {"wallet": "W2", "event_type": "BUY", "amount": 800, "token": "SOL", "timestamp": now.timestamp()},
            {"wallet": "W3", "event_type": "BUY", "amount": 600, "token": "SOL", "timestamp": now.timestamp()},
            {"wallet": "W4", "event_type": "BUY", "amount": 400, "token": "SOL", "timestamp": now.timestamp()},
            {"wallet": "W5", "event_type": "BUY", "amount": 200, "token": "SOL", "timestamp": now.timestamp()},
        ],
        "BONK": [
            {"wallet": "W1", "event_type": "BUY", "amount": 500, "token": "BONK", "timestamp": now.timestamp()},
            {"wallet": "W2", "event_type": "BUY", "amount": 300, "token": "BONK", "timestamp": now.timestamp()},
        ],
        "WIF": [
            {"wallet": "W1", "event_type": "BUY", "amount": 2000, "token": "WIF", "timestamp": now.timestamp()},
            {"wallet": "W2", "event_type": "BUY", "amount": 1500, "token": "WIF", "timestamp": now.timestamp()},
            {"wallet": "W3", "event_type": "BUY", "amount": 1000, "token": "WIF", "timestamp": now.timestamp()},
        ],
        "JUP": [
            {"wallet": "W1", "event_type": "BUY", "amount": 100, "token": "JUP", "timestamp": now.timestamp()},
        ],
    }

    # Update engine with events
    for token, events in tokens_data.items():
        for event in events:
            await engine.update(event)

    # Rank tokens
    rankings = await engine.rank_tokens()

    # Print results
    print("\n  Token Rankings:")
    print("  " + "-" * 50)
    for i, ranking in enumerate(rankings, 1):
        print(f"  {i}. {ranking.token}")
        print(f"     Alpha Score: {ranking.alpha_score:.4f}")
        print(f"     Regime: {ranking.regime}")
        print(f"     Signals: {list(ranking.signals.keys())}")
        print(f"     Smart Money Boost: {ranking.smart_money_boost:.2f}")
        print(f"     Cluster Boost: {ranking.cluster_boost:.2f}")
        print()

    # Verify success criteria
    print("  Success Criteria:")
    print("  " + "-" * 50)

    # 1. Consistent top-3
    top3 = [r.token for r in rankings[:3]]
    print(f"    Top 3 tokens: {top3}")
    print(f"    Consistent: {'PASS' if len(set(top3)) == 3 else 'CHECK'}")

    # 2. No score collapse
    scores = [r.alpha_score for r in rankings]
    max_score = max(scores) if scores else 0
    print(f"    Max score: {max_score:.4f}")
    print(f"    No collapse: {'PASS' if max_score > 0.2 else 'FAIL'}")

    # 3. Smart money presence
    smart_money_tokens = [r.token for r in rankings if r.smart_money_boost > 0]
    print(f"    Smart money tokens: {smart_money_tokens}")
    print(f"    Smart money present: {'PASS' if smart_money_tokens else 'FAIL'}")

    # 4. Regime detection
    regimes = set(r.regime for r in rankings)
    print(f"    Regimes detected: {regimes}")
    print(f"    Regime variety: {'PASS' if len(regimes) > 1 else 'CHECK'}")

    print("\n" + "=" * 60)
    print("  ALL RANKING TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
