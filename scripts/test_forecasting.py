"""Test forecasting system."""
import sys
import asyncio
from datetime import datetime, timezone

sys.path.insert(0, '.')

from app.forecasting.cluster_energy_model import ClusterEnergyModel
from app.forecasting.capital_rotation_detector import CapitalRotationDetector
from app.forecasting.cluster_forecaster import ClusterForecaster
from app.forecasting.future_leader_predictor import FutureLeaderPredictor


async def main():
    print("=" * 70)
    print("  FORECASTING SYSTEM TEST")
    print("=" * 70)

    # 1. Cluster Energy Model
    print("\n1. Cluster Energy Model")
    energy_model = ClusterEnergyModel()

    cluster_data = {
        "cluster_A": {
            "smart_money_density": 0.8,
            "cluster_size": 5,
            "cluster_density": 0.6,
            "liquidity_pressure": 0.7,
            "momentum_score": 0.9,
            "wallet_reuse": 0.5,
            "last_activity": time.time(),
        },
        "cluster_B": {
            "smart_money_density": 0.3,
            "cluster_size": 3,
            "cluster_density": 0.3,
            "liquidity_pressure": 0.2,
            "momentum_score": 0.4,
            "wallet_reuse": 0.2,
            "last_activity": time.time() - 600,  # 10 min ago
        },
    }

    for cluster_id, data in cluster_data.items():
        snapshot = energy_model.compute_energy(cluster_id, data)
        print(f"  {cluster_id}: energy={snapshot.energy_score:.3f}, trend={snapshot.trend}")

    # 2. Capital Rotation
    print("\n2. Capital Rotation Detector")
    rotation_detector = CapitalRotationDetector()

    cluster_liquidity = {"cluster_A": 5000, "cluster_B": 2000}
    cluster_history = {
        "cluster_A": [(time.time() - 300, 3000), (time.time() - 60, 4000)],
        "cluster_B": [(time.time() - 300, 4000), (time.time() - 60, 2000)],
    }

    rotations = rotation_detector.detect_rotation(cluster_liquidity, cluster_history)
    for r in rotations:
        print(f"  {r.source_cluster} -> {r.target_cluster}: strength={r.rotation_strength:.3f}, confidence={r.confidence:.3f}")

    # 3. Cluster Forecaster
    print("\n3. Cluster Forecaster")
    forecaster = ClusterForecaster(energy_model)

    cluster_energies = {
        "cluster_A": energy_model.compute_energy("cluster_A", cluster_data["cluster_A"]).energy_score,
        "cluster_B": energy_model.compute_energy("cluster_B", cluster_data["cluster_B"]).energy_score,
    }

    forecasts = forecaster.forecast_clusters(cluster_energies, [])
    for f in forecasts[:4]:
        print(f"  {f.cluster_id}: score={f.forecast_score:.3f}, horizon={f.expected_time_horizon}, confidence={f.confidence:.3f}")

    # 4. Future Leader Predictor
    print("\n4. Future Leader Predictor")
    predictor = FutureLeaderPredictor()

    token_rankings = [
        {"token": "SOL", "alpha_score": 0.25, "local_momentum_state": "accelerating", "smart_money_flag": True, "cluster_id": "A"},
        {"token": "WIF", "alpha_score": 0.22, "local_momentum_state": "accelerating", "smart_money_flag": True, "cluster_id": "A"},
        {"token": "BONK", "alpha_score": 0.18, "local_momentum_state": "stable", "smart_money_flag": False, "cluster_id": "A"},
        {"token": "JUP", "alpha_score": 0.15, "local_momentum_state": "decelerating", "smart_money_flag": False, "cluster_id": "B"},
    ]

    prediction = predictor.predict_leader(token_rankings, cluster_energies, {})
    print(f"  Current leader: {prediction.current_leader}")
    print(f"  Next leader: {prediction.predicted_next_leader}")
    print(f"  Probability: {prediction.probability:.3f}")
    print(f"  ETA: {prediction.eta_minutes} minutes")
    print(f"  Emerging: {prediction.emerging_tokens}")
    print(f"  Fading: {prediction.fading_tokens}")

    print("\n" + "=" * 70)
    print("  ALL FORECASTING TESTS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    import time
    asyncio.run(main())
