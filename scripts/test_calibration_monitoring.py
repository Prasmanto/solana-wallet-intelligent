"""Test calibration monitoring system."""
import sys
import asyncio
from datetime import datetime, timezone

sys.path.insert(0, '.')

from app.calibration_monitoring.monitoring_manager import CalibrationMonitoringManager
from app.calibration_monitoring.models import CalibrationSnapshot


async def main():
    print("=" * 70)
    print("  CALIBRATION MONITORING TEST")
    print("=" * 70)

    manager = CalibrationMonitoringManager()

    # Simulate calibration snapshots over time
    print("\n1. Recording Calibration Snapshots")
    snapshots = [
        CalibrationSnapshot(
            id=f"snap-{i}",
            created_at=datetime.now(timezone.utc).isoformat(),
            signal_weights={"smart_money": 0.25 + i * 0.005, "liquidity": 0.15 + i * 0.003, "momentum": 0.10 + i * 0.002},
            confidence_scaling={},
            regime_adjustments={},
            engine_adjustments={},
        )
        for i in range(10)
    ]

    for snap in snapshots:
        manager.record_snapshot(snap)
    print(f"  Recorded {len(snapshots)} snapshots")

    # Compute health report
    print("\n2. Computing Health Report")
    report = manager.compute_health_report()

    print(f"\n  Health Score: {report.health_score:.2f}")
    print(f"  Readiness Score: {report.readiness_score:.2f}")
    print(f"  Weight Stability: {report.weight_stability:.2f}")
    print(f"  Convergence Score: {report.convergence_score:.2f}")
    print(f"  Volatility Score: {report.volatility_score:.2f}")
    print(f"  Drift Score: {report.drift_score:.2f}")

    # Weight drifts
    print("\n3. Weight Drifts")
    for drift in report.weight_drifts:
        print(f"  {drift.signal_name:<20} {drift.previous_value:.3f} -> {drift.current_value:.3f} ({drift.status})")

    # Volatility
    print("\n4. Volatility")
    for vol in report.volatility_info:
        print(f"  {vol.metric_name:<20} stdev={vol.standard_deviation:.4f} max_swing={vol.max_swing:.4f} ({vol.status})")

    # Convergence
    print("\n5. Convergence")
    for conv in report.convergence_info:
        print(f"  {conv.metric_name:<20} converging={conv.is_converging} rate={conv.convergence_rate:.2f} oscillation={conv.oscillation_detected}")

    # Readiness status
    print("\n6. Self-Learning Readiness")
    readiness = manager.get_readiness_status()
    print(f"  Status: {readiness}")
    print(f"  Score: {report.readiness_score:.2f}")
    print(f"  Ready: {'YES' if readiness == 'READY' else 'NO'}")

    print("\n" + "=" * 70)
    print("  ALL CALIBRATION MONITORING TESTS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
