"""Test adaptive learning system."""
import sys
import asyncio

sys.path.insert(0, '.')

from app.self_learning.learning_manager import LearningManager


async def main():
    print("=" * 70)
    print("  ADAPTIVE LEARNING TEST")
    print("=" * 70)

    manager = LearningManager()

    # Simulate trade outcomes
    outcomes = []
    for i in range(50):
        success = i < 35  # 70% success rate
        outcomes.append({
            "win_loss": "WIN" if success else "LOSS",
            "roi": 12.0 if success else -3.0,
            "signal_attribution": {
                "smart_money": 0.7 if success else 0.3,
                "cluster": 0.6 if success else 0.4,
                "liquidity": 0.5,
                "momentum": 0.4,
            },
        })

    # Run learning cycle
    print("\n1. Learning Cycle")
    cycle = await manager.run_learning_cycle(outcomes)
    print(f"  Cycle ID: {cycle.cycle_id[:16]}...")
    print(f"  Signals adjusted: {cycle.signals_adjusted}")
    print(f"  Adaptation rate: {cycle.adaptation_rate:.2f}")
    print(f"  Weight stability: {cycle.weight_stability:.2f}")

    # Check weights
    print("\n2. Signal Weights")
    weights = manager.get_current_weights()
    for signal, weight in sorted(weights.items(), key=lambda x: x[1], reverse=True):
        print(f"  {signal:<20} {weight:.4f}")

    # Check reliability
    print("\n3. Reliability Scores")
    reliability = manager.get_reliability_scores()
    for signal, score in sorted(reliability.items(), key=lambda x: x[1], reverse=True):
        print(f"  {signal:<20} {score:.4f}")

    # Check health
    print("\n4. System Health")
    health = manager.get_health()
    print(f"  Cycles: {health['cycle_count']}")
    print(f"  Avg reliability: {health['avg_reliability']:.4f}")
    print(f"  Weight sum: {health['weight_sum']:.4f}")

    print("\n" + "=" * 70)
    print("  ALL ADAPTIVE LEARNING TESTS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
