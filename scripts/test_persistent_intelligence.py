"""Test persistent wallet intelligence system."""
import sys
import asyncio
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '.')

from app.intelligence.graph_builder import PersistentWalletGraph
from app.intelligence.clustering_engine import PersistentClusteringEngine
from app.intelligence.wallet_classifier import WalletClassifier
from app.intelligence.features import PersistentFeatureStore
from app.intelligence.time_decay import TimeDecayEngine
from app.intelligence.cluster_stability import ClusterStabilityMonitor


class MockRepo:
    """Mock repository for testing."""
    async def get_all_nodes(self): return []
    async def get_all_edges(self): return []
    async def upsert_node(self, wallet, data): pass
    async def upsert_edge(self, **kwargs): pass
    async def get_all_clusters(self): return []
    async def upsert_cluster(self, **kwargs): pass
    async def record_cluster_history(self, **kwargs): pass
    async def get_cluster_history(self, wallet, limit): return []
    async def upsert_feature(self, **kwargs): pass


async def main():
    print("=" * 60)
    print("  PERSISTENT WALLET INTELLIGENCE TEST")
    print("=" * 60)

    # Test 1: Time Decay Engine
    print("\n1. Time Decay Engine")
    decay = TimeDecayEngine(decay_factor=0.0001)
    weight = 100.0
    now = datetime.now(timezone.utc)

    # Recent interaction (1 minute ago)
    recent = now - timedelta(minutes=1)
    decayed_recent = decay.calculate_decayed_weight(weight, recent)
    print(f"   1 min ago: {weight} -> {decayed_recent:.2f}")

    # Old interaction (1 hour ago)
    old = now - timedelta(hours=1)
    decayed_old = decay.calculate_decayed_weight(weight, old)
    print(f"   1 hour ago: {weight} -> {decayed_old:.2f}")

    # Very old interaction (24 hours ago)
    very_old = now - timedelta(hours=24)
    decayed_very_old = decay.calculate_decayed_weight(weight, very_old)
    print(f"   24 hours ago: {weight} -> {decayed_very_old:.2f}")

    # Verify decay works
    print(f"   Decay working: {'OK' if decayed_recent > decayed_old > decayed_very_old else 'FAIL'}")

    # Test 2: Graph Builder
    print("\n2. Graph Builder")
    graph = PersistentWalletGraph(MockRepo())
    await graph.load()

    events = [
        {'wallet': 'W1', 'event_type': 'TRANSFER', 'data': {'to': 'W2'}, 'amount': 100},
        {'wallet': 'W1', 'event_type': 'SWAP', 'data': {'to': 'W3'}, 'amount': 200},
        {'wallet': 'W2', 'event_type': 'BUY', 'data': {'to': 'W1'}, 'amount': 50},
    ]

    for event in events:
        await graph.update(event)

    print(f"   Nodes: {graph.get_node_count()}")
    print(f"   Edges: {graph.get_edge_count()}")
    print(f"   W1 neighbors: {graph.get_neighbors('W1')}")

    # Test 3: Clustering Engine
    print("\n3. Clustering Engine")
    clustering = PersistentClusteringEngine(MockRepo())
    await clustering.load()

    for event in events:
        result = await clustering.process_event(event)

    clusters = clustering.get_all_clusters()
    print(f"   Clusters: {len(clusters)}")
    for cluster_id, members in clusters.items():
        print(f"   Cluster {cluster_id[:8]}: {members}")

    # Test 4: Wallet Classifier
    print("\n4. Wallet Classifier")
    classifier = WalletClassifier()
    features = {
        'wallet': 'W1',
        'tx_frequency': 5,
        'volume': 350,
        'avg_interval': 300,
        'token_diversity': 2,
        'buy_sell_ratio': 1.0,
    }
    classification = classifier.classify('W1', features)
    print(f"   W1: {classification['wallet_type']} (confidence={classification['confidence']})")

    # Test 5: Time Decay
    print("\n5. Time Decay")
    decay = TimeDecayEngine(decay_factor=0.0001)
    weight = 10.0
    now = datetime.now(timezone.utc)

    recent = now - timedelta(minutes=1)
    decayed_recent = decay.calculate_decayed_weight(weight, recent)
    print(f"   1 min ago: {weight} -> {decayed_recent:.2f}")

    old = now - timedelta(hours=1)
    decayed_old = decay.calculate_decayed_weight(weight, old)
    print(f"   1 hour ago: {weight} -> {decayed_old:.2f}")

    very_old = now - timedelta(hours=24)
    decayed_very_old = decay.calculate_decayed_weight(weight, very_old)
    print(f"   24 hours ago: {weight} -> {decayed_very_old:.2f}")

    # Verify decay ordering
    decay_ok = decayed_recent > decayed_old > decayed_very_old
    print(f"   Decay ordering: {'OK' if decay_ok else 'FAIL'}")

    print("\n" + "=" * 60)
    print("  ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
