"""Test pump prediction with strong multi-signal scenario."""
import sys
import asyncio
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '.')

from app.pump_prediction.pump_prediction_engine import PumpPredictionEngine


async def main():
    print("=" * 60)
    print("  MULTI-SIGNAL PUMP PREDICTION TEST")
    print("=" * 60)

    engine = PumpPredictionEngine()

    # Create events that trigger multiple signals
    now = datetime.now(timezone.utc)
    events = []

    # Strong accumulation pattern (triggers liquidity + momentum)
    for i in range(30):
        ts = now - timedelta(minutes=i)
        events.append({
            'wallet': f'W{i % 5}',
            'event_type': 'BUY',
            'amount': 300 + i * 50,  # Strong increasing pattern
            'token': 'STRONG_TOKEN',
            'timestamp': ts.timestamp(),
        })

    # Create cluster events (triggers cluster convergence)
    cluster_events = {}
    for wallet in ['W0', 'W1', 'W2', 'W3']:
        wallet_events = []
        for i in range(20):
            ts = now - timedelta(minutes=i)
            wallet_events.append({
                'wallet': wallet,
                'event_type': 'BUY',
                'amount': 200 + i * 30,
                'token': 'STRONG_TOKEN',
                'timestamp': ts.timestamp(),
            })
        cluster_events[wallet] = wallet_events

    # Pre-populate historical baseline for anomaly detection
    engine._anomaly_detector._baseline_history['STRONG_TOKEN'] = [
        {'volume': 100, 'tx_count': 5, 'wallet_count': 2, 'avg_amount': 20}
        for _ in range(10)
    ]

    # Analyze
    signal = await engine.analyze(events[0], cluster_events)

    if signal:
        print(f"\n  Token: {signal['token']}")
        print(f"  Score: {signal['score']:.4f}")
        print(f"  Conviction: {signal['conviction']:.4f}")
        print(f"  Stage: {signal['stage']}")
        print(f"  Signal Strength: {signal['signal_strength']}")
        print(f"  Recommendation: {signal['recommendation']}")
        print(f"  Signals: {signal['signals']}")
        print(f"  Signal Count: {signal['signal_count']}")
        print(f"\n  Score Breakdown:")
        for key, value in signal.get('score_breakdown', {}).items():
            print(f"    {key}: {value:.4f}")

        # Verify improvements
        print(f"\n  Verification:")
        print(f"    Score > 0.05: {'PASS' if signal['score'] > 0.05 else 'FAIL'}")
        print(f"    Conviction > 0: {'PASS' if signal['conviction'] > 0 else 'FAIL'}")
        print(f"    Multiple signals: {'PASS' if signal['signal_count'] >= 2 else 'FAIL'}")
    else:
        print("  No signal detected")

    print("\n" + "=" * 60)
    print("  TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
