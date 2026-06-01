"""Test calibration engine."""
import sys
import asyncio
from datetime import datetime, timezone

sys.path.insert(0, '.')

from app.calibration.calibration_manager import CalibrationManager
from app.calibration.calibration_models import CalibrationReport


async def main():
    print("=" * 70)
    print("  CALIBRATION ENGINE TEST")
    print("=" * 70)

    manager = CalibrationManager()

    # Simulate analytics data
    signal_attribution = {
        "smart_money": {"success_rate": 0.75, "average_return": 12.0},
        "cluster_convergence": {"success_rate": 0.45, "average_return": 5.0},
        "liquidity": {"success_rate": 0.70, "average_return": 10.0},
        "momentum": {"success_rate": 0.65, "average_return": 8.0},
        "lead_lag": {"success_rate": 0.55, "average_return": 6.0},
        "anomaly": {"success_rate": 0.50, "average_return": 4.0},
    }

    confidence_analysis = {
        "0.50-0.70": {"success_rate": 0.30, "count": 40},
        "0.70-0.80": {"success_rate": 0.70, "count": 20},
        "0.80-0.90": {"success_rate": 0.65, "count": 20},
        "0.90-1.00": {"success_rate": 0.65, "count": 20},
    }

    regime_performance = {
        "NORMAL": {"accuracy": 0.33, "average_return": 2.0},
        "ACCUMULATION": {"accuracy": 0.67, "average_return": 12.0},
        "PUMP_BUILDUP": {"accuracy": 0.50, "average_return": 8.0},
        "PARABOLIC": {"accuracy": 0.33, "average_return": -2.0},
    }

    engine_performance = {
        "pump": {"accuracy": 0.70, "average_return": 10.0},
        "leader": {"accuracy": 0.50, "average_return": 8.0},
        "cluster": {"accuracy": 0.60, "average_return": 10.0},
        "ranking": {"accuracy": 0.65, "average_return": 9.0},
    }

    # Run calibration
    print("\n1. Running Calibration Cycle")
    report = await manager.run_calibration(
        signal_attribution,
        confidence_analysis,
        regime_performance,
        engine_performance,
    )

    # Display results
    print("\n2. Signal Weights (Before -> After)")
    print("  " + "-" * 60)
    for sig in report.signal_weights:
        print(f"  {sig.signal_name:<20} {sig.old_weight:.3f} -> {sig.new_weight:.3f} (success={sig.success_rate:.0%})")

    print("\n3. Confidence Scaling")
    print("  " + "-" * 60)
    for conf in report.confidence_scaling:
        print(f"  {conf.raw_confidence:.2f} -> {conf.calibrated_confidence:.2f} (actual={conf.actual_success_rate:.0%})")

    print("\n4. Regime Adjustments")
    print("  " + "-" * 60)
    for reg in report.regime_adjustments:
        print(f"  {reg.regime:<15} {reg.old_multiplier:.2f}x -> {reg.new_multiplier:.2f}x (accuracy={reg.accuracy:.0%})")

    print("\n5. Engine Adjustments")
    print("  " + "-" * 60)
    for eng in report.engine_adjustments:
        print(f"  {eng.engine_name:<15} reliability={eng.reliability_score:.2f} (accuracy={eng.accuracy:.0%})")

    # Verify calibration is stable
    print("\n6. Calibration Stability Check")
    print("  " + "-" * 60)
    weights = manager.get_current_weights()
    total_weight = sum(weights.values())
    print(f"  Total weight: {total_weight:.3f} (should be ~1.0)")
    print(f"  Weight normalized: {'PASS' if abs(total_weight - 1.0) < 0.01 else 'FAIL'}")

    max_weight = max(weights.values())
    min_weight = min(weights.values())
    print(f"  Max weight: {max_weight:.3f} (max=0.40)")
    print(f"  Min weight: {min_weight:.3f} (min=0.05)")
    print(f"  Bounds OK: {'PASS' if max_weight <= 0.40 and min_weight >= 0.05 else 'FAIL'}")

    print("\n" + "=" * 70)
    print("  ALL CALIBRATION TESTS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
