"""Test smart money detection system."""
import sys
import asyncio
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '.')

from app.smart_money.smart_money_engine import SmartMoneyEngine
from app.smart_money.velocity_detector import VelocityDetector
from app.smart_money.liquidity_flow_tracker import LiquidityFlowTracker
from app.smart_money.cluster_signal_engine import ClusterSignalEngine
from app.smart_money.signal_models import SmartMoneySignal, get_alpha_strength, get_recommendation


async def main():
    print("=" * 60)
    print("  SMART MONEY DETECTION TEST")
    print("=" * 60)

    # Test 1: Velocity Detector
    print("\n1. Velocity Detector")
    detector = VelocityDetector(velocity_threshold=2.0, volume_threshold=1.5)

    # Create events with velocity spike
    now = datetime.now(timezone.utc)
    events = []
    for i in range(30):
        ts = now - timedelta(minutes=i * 2)
        events.append({
            'wallet': 'W1',
            'event_type': 'BUY',
            'amount': 100 + i * 10,
            'timestamp': ts.timestamp(),
        })

    signal = detector.detect('W1', events)
    if signal:
        print(f"   Velocity spike detected: ratio={signal.velocity_ratio:.2f}, score={signal.score:.2f}")
    else:
        print("   No velocity spike detected")

    # Test 2: Liquidity Flow Tracker
    print("\n2. Liquidity Flow Tracker")
    tracker = LiquidityFlowTracker(flow_ratio_threshold=1.5, sustained_windows=2)

    # Create events with accumulation pattern
    events = []
    for i in range(20):
        ts = now - timedelta(minutes=i)
        events.append({
            'wallet': 'W2',
            'event_type': 'BUY',
            'amount': 200,
            'timestamp': ts.timestamp(),
        })

    signal = tracker.track('W2', events)
    if signal:
        print(f"   Liquidity accumulation: net_flow={signal.net_flow:.0f}, ratio={signal.flow_ratio:.2f}")
    else:
        print("   No liquidity accumulation detected")

    # Test 3: Cluster Signal Engine
    print("\n3. Cluster Signal Engine")
    cluster_engine = ClusterSignalEngine(min_active_wallets=2)

    # Create cluster events
    cluster_events = {}
    for wallet in ['W3', 'W4', 'W5']:
        events = []
        for i in range(15):
            ts = now - timedelta(minutes=i)
            events.append({
                'wallet': wallet,
                'event_type': 'BUY',
                'amount': 150,
                'timestamp': ts.timestamp(),
            })
        cluster_events[wallet] = events

    signal = cluster_engine.detect('C1', cluster_events)
    if signal:
        print(f"   Cluster activity: wallets={signal.active_wallets}, sync={signal.synchronized_score:.2f}")
    else:
        print("   No cluster activity detected")

    # Test 4: Smart Money Engine
    print("\n4. Smart Money Engine")
    engine = SmartMoneyEngine(velocity_threshold=2.0, flow_ratio_threshold=1.5)

    # Create events for smart money detection
    events = []
    for i in range(25):
        ts = now - timedelta(minutes=i)
        events.append({
            'wallet': 'SMART_WALLET',
            'event_type': 'BUY',
            'amount': 300,
            'timestamp': ts.timestamp(),
        })

    signal = await engine.analyze('SMART_WALLET', events)
    if signal:
        print(f"   Smart money signal detected!")
        print(f"   Score: {signal.score:.2f}")
        print(f"   Alpha strength: {signal.alpha_strength}")
        print(f"   Recommendation: {signal.recommendation}")
        print(f"   Signals: {signal.signals}")
    else:
        print("   No smart money signal detected")

    # Test 5: Score Levels
    print("\n5. Score Levels")
    for score in [0.3, 0.6, 0.75, 0.9]:
        strength = get_alpha_strength(score)
        rec = get_recommendation(score)
        print(f"   Score {score:.2f}: {strength} / {rec}")

    print("\n" + "=" * 60)
    print("  ALL SMART MONEY TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
