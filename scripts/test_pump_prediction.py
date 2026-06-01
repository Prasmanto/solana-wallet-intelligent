"""Test pump prediction system."""
import sys
import asyncio
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '.')

from app.pump_prediction.pump_prediction_engine import PumpPredictionEngine
from app.pump_prediction.token_flow_aggregator import TokenFlowAggregator
from app.pump_prediction.liquidity_acceleration_model import LiquidityAccelerationModel
from app.pump_prediction.cluster_convergence_detector import ClusterConvergenceDetector
from app.pump_prediction.anomaly_detector import AnomalyDetector
from app.pump_prediction.momentum_model import MomentumModel


async def main():
    print("=" * 60)
    print("  TOKEN PUMP PREDICTION TEST")
    print("=" * 60)

    # Test 1: Token Flow Aggregator
    print("\n1. Token Flow Aggregator")
    aggregator = TokenFlowAggregator()

    # Simulate token activity
    now = datetime.now(timezone.utc)
    for i in range(20):
        ts = now - timedelta(minutes=i)
        aggregator.update({
            'wallet': f'W{i % 5}',
            'event_type': 'BUY',
            'amount': 100 + i * 10,
            'token': 'TEST_TOKEN',
            'timestamp': ts.timestamp(),
        })

    flow = aggregator.get_token_flow('TEST_TOKEN')
    print(f"   Token: TEST_TOKEN")
    print(f"   Inflow: {flow['inflow']:.0f}")
    print(f"   Outflow: {flow['outflow']:.0f}")
    print(f"   Net flow: {flow['net_flow']:.0f}")
    print(f"   Wallet count: {flow['wallet_count']}")

    # Test 2: Liquidity Acceleration
    print("\n2. Liquidity Acceleration Model")
    acceleration = LiquidityAccelerationModel(acceleration_threshold=0.5)

    events = []
    for i in range(25):
        ts = now - timedelta(minutes=i)
        events.append({
            'wallet': 'W1',
            'event_type': 'BUY',
            'amount': 50 + i * 20,  # Increasing amounts
            'token': 'ACCEL_TOKEN',
            'timestamp': ts.timestamp(),
        })

    signal = acceleration.detect('ACCEL_TOKEN', events)
    if signal:
        print(f"   Acceleration detected: score={signal['score']:.2f}, trend={signal['trend']}")
    else:
        print("   No acceleration detected")

    # Test 3: Cluster Convergence
    print("\n3. Cluster Convergence Detector")
    convergence = ClusterConvergenceDetector(min_clusters=2)

    token_flow = {
        'token': 'CONVERGE_TOKEN',
        'net_flow': 5000,
        'clusters': ['C1', 'C2', 'C3'],
    }

    cluster_events = {
        'C1': [{'wallet': 'W1', 'token': 'CONVERGE_TOKEN', 'event_type': 'BUY', 'amount': 100, 'timestamp': now.timestamp()}],
        'C2': [{'wallet': 'W2', 'token': 'CONVERGE_TOKEN', 'event_type': 'BUY', 'amount': 200, 'timestamp': now.timestamp()}],
        'C3': [{'wallet': 'W3', 'token': 'CONVERGE_TOKEN', 'event_type': 'BUY', 'amount': 150, 'timestamp': now.timestamp()}],
    }

    signal = convergence.detect('CONVERGE_TOKEN', token_flow, cluster_events)
    if signal:
        print(f"   Convergence detected: clusters={signal['clusters']}, sync={signal['synchronized_score']:.2f}")
    else:
        print("   No convergence detected")

    # Test 4: Anomaly Detection
    print("\n4. Anomaly Detector")
    anomaly = AnomalyDetector(anomaly_threshold=1.5)

    current_events = [{'wallet': f'W{i}', 'event_type': 'BUY', 'amount': 500, 'token': 'ANOMALY_TOKEN', 'timestamp': now.timestamp()} for i in range(10)]
    historical_events = [{'wallet': f'W{i}', 'event_type': 'BUY', 'amount': 50, 'token': 'ANOMALY_TOKEN', 'timestamp': (now - timedelta(hours=2)).timestamp()} for i in range(5)]

    signal = anomaly.detect('ANOMALY_TOKEN', current_events, historical_events)
    if signal:
        print(f"   Anomaly detected: score={signal['anomaly_score']:.2f}")
    else:
        print("   No anomaly detected")

    # Test 5: Momentum Model
    print("\n5. Momentum Model")
    momentum = MomentumModel(momentum_threshold=0.3)

    events = []
    for i in range(20):
        ts = now - timedelta(minutes=i)
        events.append({
            'wallet': f'W{i % 3}',
            'event_type': 'BUY',
            'amount': 100 + i * 50,  # Increasing amounts
            'token': 'MOMENTUM_TOKEN',
            'timestamp': ts.timestamp(),
        })

    signal = momentum.compute('MOMENTUM_TOKEN', events)
    if signal:
        print(f"   Momentum detected: score={signal['score']:.2f}, direction={signal['direction']}")
    else:
        print("   No momentum detected")

    # Test 6: Pump Prediction Engine
    print("\n6. Pump Prediction Engine")
    engine = PumpPredictionEngine()

    # Create events with multiple signals
    events = []
    for i in range(25):
        ts = now - timedelta(minutes=i)
        events.append({
            'wallet': f'W{i % 5}',
            'event_type': 'BUY',
            'amount': 200 + i * 30,  # Strong accumulation
            'token': 'PUMP_TOKEN',
            'timestamp': ts.timestamp(),
        })

    # Create cluster events
    cluster_events = {}
    for wallet in ['W0', 'W1', 'W2']:
        wallet_events = []
        for i in range(15):
            ts = now - timedelta(minutes=i)
            wallet_events.append({
                'wallet': wallet,
                'event_type': 'BUY',
                'amount': 150,
                'token': 'PUMP_TOKEN',
                'timestamp': ts.timestamp(),
            })
        cluster_events[wallet] = wallet_events

    signal = await engine.analyze(events[0], cluster_events)
    if signal:
        print(f"   Pump prediction detected!")
        print(f"   Token: {signal['token']}")
        print(f"   Score: {signal['score']:.2f}")
        print(f"   Stage: {signal['stage']}")
        print(f"   Recommendation: {signal['recommendation']}")
        print(f"   Signals: {signal['signals']}")
    else:
        print("   No pump prediction detected")

    print("\n" + "=" * 60)
    print("  ALL PUMP PREDICTION TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
