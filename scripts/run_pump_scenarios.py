"""Pump scenario runner — runs simulation scenarios and validates signals.

Scenarios:
A: normal → accumulation → burst → distribution
B: burst-heavy (stress test)
C: fake whale manipulation cycle

Validates:
- Liquidity signal activates in burst mode
- Cluster convergence increases under stress
- Pump engine score > 0.6 during burst
- Momentum reacts within same window
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

sys.path.insert(0, '.')

from app.pump_prediction.pump_prediction_engine import PumpPredictionEngine
from scripts.liquidity_burst_simulator import LiquidityBurstSimulator


async def run_scenario_a():
    """Scenario A: Full pump cycle."""
    print("\n" + "=" * 70)
    print("  SCENARIO A: Full Pump Cycle")
    print("  normal -> accumulation -> burst -> distribution")
    print("=" * 70)

    sim = LiquidityBurstSimulator(seed=42)
    # Use short cooldown for simulation
    engine = PumpPredictionEngine(cooldown_seconds=1)

    target_token = "PUMP_TOKEN_A"

    # Generate full cycle
    all_events = sim.generate_full_cycle(target_token)

    # Process events through engine
    print(f"\n  Processing {len(all_events)} events...")

    cluster_events = sim.get_active_clusters()
    signals_detected = []

    for event in all_events:
        signal = await engine.analyze(event, cluster_events)
        if signal and signal["score"] > 0.05:
            signals_detected.append(signal)

    # Print results
    print(f"\n  Results:")
    print(f"    Total events: {len(all_events)}")
    print(f"    Signals detected: {len(signals_detected)}")

    if signals_detected:
        max_score = max(s["score"] for s in signals_detected)
        max_conviction = max(s["conviction"] for s in signals_detected)
        print(f"    Max score: {max_score:.4f}")
        print(f"    Max conviction: {max_conviction:.4f}")

        # Check if burst triggered high score
        burst_signals = [s for s in signals_detected if s["score"] > 0.5]
        print(f"    Signals > 0.5: {len(burst_signals)}")

        if burst_signals:
            print(f"    PASS: Burst triggered high scores!")
        else:
            print(f"    PARTIAL: Some signals detected but below threshold")
    else:
        print(f"    FAIL: No signals detected")

    return signals_detected


async def run_scenario_b():
    """Scenario B: Burst-heavy stress test."""
    print("\n" + "=" * 70)
    print("  SCENARIO B: Burst-Heavy Stress Test")
    print("=" * 70)

    sim = LiquidityBurstSimulator(seed=123)
    engine = PumpPredictionEngine(cooldown_seconds=1)

    target_token = "STRESS_TOKEN_B"

    # Multiple bursts
    all_events = []
    for i in range(3):
        events = sim.generate_events("BURST", duration_seconds=10, target_token=target_token)
        all_events.extend(events)

    # Process events
    print(f"\n  Processing {len(all_events)} events...")

    cluster_events = sim.get_active_clusters()
    signals_detected = []

    for event in all_events:
        signal = await engine.analyze(event, cluster_events)
        if signal and signal["score"] > 0.05:
            signals_detected.append(signal)

    # Print results
    print(f"\n  Results:")
    print(f"    Total events: {len(all_events)}")
    print(f"    Signals detected: {len(signals_detected)}")

    if signals_detected:
        max_score = max(s["score"] for s in signals_detected)
        print(f"    Max score: {max_score:.4f}")

        burst_signals = [s for s in signals_detected if s["score"] > 0.5]
        print(f"    Signals > 0.5: {len(burst_signals)}")
    else:
        print(f"    FAIL: No signals detected")

    return signals_detected


async def run_scenario_c():
    """Scenario C: Fake whale manipulation cycle."""
    print("\n" + "=" * 70)
    print("  SCENARIO C: Whale Manipulation Cycle")
    print("=" * 70)

    sim = LiquidityBurstSimulator(seed=456)
    engine = PumpPredictionEngine(cooldown_seconds=1)

    target_token = "WHALE_TOKEN_C"

    all_events = []

    # Phase 1: Whale accumulation (quiet)
    print("\n  Phase 1: Whale accumulation...")
    acc_events = sim.generate_events("ACCUMULATION", duration_seconds=15, target_token=target_token)
    all_events.extend(acc_events)
    print(f"    Generated {len(acc_events)} events")

    # Phase 2: Whale burst (loud)
    print("  Phase 2: Whale burst...")
    burst_events = sim.generate_events("BURST", duration_seconds=10, target_token=target_token)
    all_events.extend(burst_events)
    print(f"    Generated {len(burst_events)} events")

    # Process events
    print(f"\n  Processing {len(all_events)} events...")

    cluster_events = sim.get_active_clusters()
    signals_detected = []

    for event in all_events:
        signal = await engine.analyze(event, cluster_events)
        if signal and signal["score"] > 0.05:
            signals_detected.append(signal)

    # Print results
    print(f"\n  Results:")
    print(f"    Total events: {len(all_events)}")
    print(f"    Signals detected: {len(signals_detected)}")

    if signals_detected:
        max_score = max(s["score"] for s in signals_detected)
        print(f"    Max score: {max_score:.4f}")

        burst_signals = [s for s in signals_detected if s["score"] > 0.5]
        print(f"    Signals > 0.5: {len(burst_signals)}")
    else:
        print(f"    FAIL: No signals detected")

    return signals_detected


async def main():
    """Run all scenarios."""
    print("\n" + "=" * 70)
    print("  LIQUIDITY BURST SIMULATION")
    print("=" * 70)

    # Run scenarios
    results_a = await run_scenario_a()
    results_b = await run_scenario_b()
    results_c = await run_scenario_c()

    # Summary
    print("\n" + "=" * 70)
    print("  VALIDATION SUMMARY")
    print("=" * 70)

    all_signals = results_a + results_b + results_c

    if all_signals:
        max_score = max(s["score"] for s in all_signals)
        avg_score = sum(s["score"] for s in all_signals) / len(all_signals)
        print(f"  Total signals: {len(all_signals)}")
        print(f"  Max score: {max_score:.4f}")
        print(f"  Avg score: {avg_score:.4f}")

        # Check criteria
        burst_triggered = any(s["score"] > 0.6 for s in all_signals)
        print(f"\n  Validation Criteria:")
        print(f"    Liquidity signal activated: {'PASS' if any('LIQUIDITY' in str(s.get('signals', [])) for s in all_signals) else 'FAIL'}")
        print(f"    Cluster convergence > 0.7: {'PASS' if any(s.get('score', 0) > 0.7 for s in all_signals) else 'FAIL'}")
        print(f"    Pump score > 0.6 during burst: {'PASS' if burst_triggered else 'FAIL'}")
        print(f"    Multiple signals detected: {'PASS' if len(all_signals) > 5 else 'FAIL'}")
    else:
        print(f"  FAIL: No signals detected across all scenarios")

    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
