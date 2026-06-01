"""Test pump prediction with comprehensive multi-signal scenario."""
import sys
import asyncio
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '.')

from app.pump_prediction.pump_prediction_engine import PumpPredictionEngine
from app.pump_prediction.token_flow_aggregator import TokenFlowAggregator
from app.pump_prediction.liquidity_acceleration_model import LiquidityAccelerationModel
from app.pump_prediction.cluster_convergence_detector import ClusterConvergenceDetector
import time


async def main():
    print("=" * 60)
    print("  COMPREHENSIVE MULTI-SIGNAL TEST")
    print("=" * 60)

    # Test individual signal detectors first
    print("\n1. Testing individual detectors...")

    # Liquidity Acceleration
    liq = LiquidityAccelerationModel(acceleration_threshold=0.5)
    now = datetime.now(timezone.utc)
    events = []
    for i in range(25):
        ts = now - timedelta(minutes=i)
        events.append({
            'wallet': 'W1',
            'event_type': 'BUY',
            'amount': 100 + i * 30,
            'token': 'TEST',
            'timestamp': ts.timestamp(),
        })
    liq_signal = liq.detect('TEST', events)
    print(f"   Liquidity: {liq_signal is not None} (score={liq_signal.get('score', 0) if liq_signal else 0})")

    # Cluster Convergence
    cluster = ClusterConvergenceDetector(min_clusters=2)
    token_flow = {
        'token': 'TEST',
        'net_flow': 5000,
        'clusters': ['C1', 'C2', 'C3'],
    }
    cluster_events = {
        'C1': [{'wallet': 'W1', 'token': 'TEST', 'event_type': 'BUY', 'amount': 200, 'timestamp': now.timestamp()}],
        'C2': [{'wallet': 'W2', 'token': 'TEST', 'event_type': 'BUY', 'amount': 300, 'timestamp': now.timestamp()}],
        'C3': [{'wallet': 'W3', 'token': 'TEST', 'event_type': 'BUY', 'amount': 250, 'timestamp': now.timestamp()}],
    }
    cluster_signal = cluster.detect('TEST', token_flow, cluster_events)
    print(f"   Cluster: {cluster_signal is not None} (score={cluster_signal.get('score', 0) if cluster_signal else 0})")

    # Test full engine
    print("\n2. Testing full engine...")

    engine = PumpPredictionEngine()

    # Pre-populate baselines for anomaly detection
    # The baseline needs to be in the format that _calculate_metrics expects
    engine._anomaly_detector._baseline_history['STRONG_TOKEN'] = [
        {'volume': 100, 'tx_count': 5, 'wallet_count': 2, 'avg_amount': 20}
        for _ in range(10)
    ]

    # Debug: manually test anomaly detector
    print("\n   Debug: Testing anomaly detector manually...")
    test_events = [{'wallet': 'W1', 'event_type': 'BUY', 'amount': 500, 'token': 'STRONG_TOKEN', 'timestamp': now.timestamp()}]
    baseline = engine._anomaly_detector._get_baseline('STRONG_TOKEN')
    print(f"   Baseline: {baseline}")
    current = engine._anomaly_detector._calculate_metrics(test_events)
    print(f"   Current: {current}")
    score = engine._anomaly_detector._calculate_anomaly_score(current, baseline)
    print(f"   Raw score: {score}")
    print(f"   Threshold: {engine._anomaly_detector._anomaly_threshold}")

    # Create events
    now = datetime.now(timezone.utc)
    events = []
    # Create events spanning multiple time windows (5m, 15m, 30m, 60m)
    for i in range(60):
        ts = now - timedelta(minutes=i)
        events.append({
            'wallet': f'W{i % 5}',
            'event_type': 'BUY',
            'amount': 500 + i * 100,  # Stronger pattern
            'token': 'STRONG_TOKEN',
            'timestamp': ts.timestamp(),
        })

    cluster_events = {}
    for wallet in ['W0', 'W1', 'W2', 'W3', 'W4']:
        wallet_events = []
        for i in range(30):
            ts = now - timedelta(minutes=i)
            wallet_events.append({
                'wallet': wallet,
                'event_type': 'BUY',
                'amount': 400 + i * 60,
                'token': 'STRONG_TOKEN',
                'timestamp': ts.timestamp(),
            })
        cluster_events[wallet] = wallet_events

    # Analyze
    signal = await engine.analyze(events[0], cluster_events)

    if signal:
        print(f"\n   Token: {signal['token']}")
        print(f"   Score: {signal['score']:.4f}")
        print(f"   Conviction: {signal['conviction']:.4f}")
        print(f"   Stage: {signal['stage']}")
        print(f"   Signal Strength: {signal['signal_strength']}")
        print(f"   Recommendation: {signal['recommendation']}")
        print(f"   Signals: {signal['signals']}")
        print(f"   Signal Count: {signal['signal_count']}")
        print(f"\n   Score Breakdown:")
        for key, value in signal.get('score_breakdown', {}).items():
            print(f"     {key}: {value:.4f}")
    else:
        print("   No signal detected")

    print("\n" + "=" * 60)
    print("  TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
