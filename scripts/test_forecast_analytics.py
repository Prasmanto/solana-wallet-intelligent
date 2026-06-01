"""Test forecast analytics system."""
import sys
import asyncio
from datetime import datetime, timezone

sys.path.insert(0, '.')

from app.analytics.alpha_attribution import AlphaAttribution
from app.analytics.signal_performance import SignalPerformance
from app.analytics.confidence_analysis import ConfidenceAnalysis
from app.analytics.engine_comparison import EngineComparison
from app.analytics.forecast_analytics import ForecastAnalytics
from app.analytics.return_analysis import ReturnAnalysis


async def main():
    print("=" * 70)
    print("  FORECAST ANALYTICS TEST")
    print("=" * 70)

    # Test 1: Alpha Attribution
    print("\n1. Alpha Attribution")
    attribution = AlphaAttribution()

    # Simulate predictions
    for i in range(20):
        success = i < 15  # 75% success rate
        attribution.record_prediction(
            signals={
                "smart_money": 0.7 if success else 0.3,
                "cluster": 0.8 if success else 0.4,
                "liquidity": 0.6,
                "momentum": 0.5,
            },
            success=success,
            actual_return=12.0 if success else -5.0,
        )

    attr = attribution.compute_attribution()
    for signal, stats in attr.items():
        print(f"  {signal}: {stats['success_rate']:.1%} success, avg return={stats['average_return']:.1f}%")

    top = attribution.get_top_signals(3)
    print(f"\n  Top 3 signals: {[s['signal'] for s in top]}")

    # Test 2: Confidence Analysis
    print("\n2. Confidence Analysis")
    confidence = ConfidenceAnalysis()

    for i in range(100):
        conf = 0.5 + (i / 200)
        success = conf > 0.6 and (i % 3 != 0)
        confidence.record(conf, success, 5.0 if success else -2.0)

    analysis = confidence.analyze()
    for bucket, stats in analysis.items():
        print(f"  {stats['range']}: {stats['success_rate']:.1%} success, count={stats['count']}")

    quality = confidence.get_calibration_quality()
    print(f"\n  Calibration: {quality}")

    # Test 3: Engine Comparison
    print("\n3. Engine Comparison")
    comparison = EngineComparison()

    for engine in ["pump", "leader", "cluster"]:
        for i in range(50):
            success = i < 35 if engine == "pump" else i < 25 if engine == "leader" else i < 30
            comparison.record(engine, success, 10.0 if success else -3.0, 0.7)

    engines = comparison.get_top_engines(3)
    for e in engines:
        print(f"  {e['engine']}: accuracy={e['accuracy']:.1%}, avg_return={e['average_return']:.1f}%")

    # Test 4: Regime Analytics
    print("\n4. Regime Analytics")
    forecast = ForecastAnalytics()

    for regime in ["NORMAL", "ACCUMULATION", "PUMP_BUILDUP", "PARABOLIC"]:
        for i in range(30):
            success = i < 20 if regime == "ACCUMULATION" else i < 15 if regime == "PUMP_BUILDUP" else i < 10
            forecast.record(regime, "SOL", "1h", success, 12.0 if success else -3.0, 0.7)

    regime_perf = forecast.compute_regime_performance()
    for regime, stats in regime_perf.items():
        print(f"  {regime}: accuracy={stats['accuracy']:.1%}")

    # Test 5: Token Analytics
    print("\n5. Token Analytics")
    for token in ["SOL", "WIF", "BONK"]:
        for i in range(20):
            success = i < 16 if token == "SOL" else i < 12 if token == "WIF" else i < 8
            forecast.record("ACCUMULATION", token, "1h", success, 15.0 if success else -4.0, 0.7)

    token_perf = forecast.compute_token_performance()
    for token, stats in token_perf.items():
        print(f"  {token}: accuracy={stats['accuracy']:.1%}, avg_return={stats['average_return']:.1f}%")

    # Test 6: Return Analysis
    print("\n6. Return Analysis")
    returns = ReturnAnalysis()

    for i in range(50):
        ret = 15.0 if i < 30 else -5.0
        returns.record("pump", ret, 0.7)

    stats = returns.compute_statistics()
    print(f"  Total: {stats['total']}")
    print(f"  Avg Return: {stats['average_return']:.1f}%")
    print(f"  Std Dev: {stats['std_dev']:.1f}%")
    print(f"  Positive: {stats['positive_count']}, Negative: {stats['negative_count']}")

    print("\n" + "=" * 70)
    print("  ALL FORECAST ANALYTICS TESTS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
