"""Test intelligence module."""
import sys
sys.path.insert(0, '.')

from app.intelligence.graph_builder import WalletGraph
from app.intelligence.clustering_engine import ClusteringEngine
from app.intelligence.wallet_classifier import WalletClassifier
from app.intelligence.features import FeatureExtractor

print("Testing Graph Builder...")
graph = WalletGraph()

events = [
    {'wallet': 'W1', 'event_type': 'TRANSFER', 'data': {'to': 'W2'}, 'amount': 100},
    {'wallet': 'W1', 'event_type': 'SWAP', 'data': {'to': 'W3'}, 'amount': 200},
    {'wallet': 'W2', 'event_type': 'BUY', 'data': {'to': 'W1'}, 'amount': 50},
    {'wallet': 'W3', 'event_type': 'SELL', 'data': {'to': 'W1'}, 'amount': 150},
    {'wallet': 'W4', 'event_type': 'TRANSFER', 'data': {'to': 'W5'}, 'amount': 300},
]

for event in events:
    graph.update(event)

print(f"  Nodes: {graph.get_node_count()}")
print(f"  Edges: {graph.get_edge_count()}")
print(f"  W1 neighbors: {graph.get_neighbors('W1')}")

print("\nTesting Clustering Engine...")
clustering = ClusteringEngine(threshold=0.65)

for event in events:
    result = clustering.process_event(event)
    if result:
        print(f"  {result['wallet'][:4]} -> cluster {result['cluster_id'][:8]} (size={result['cluster_size']})")

clusters = clustering.get_all_clusters()
print(f"  Total clusters: {len(clusters)}")

print("\nTesting Feature Extractor...")
features = FeatureExtractor()
wallet_features = features.extract('W1', events)
print(f"  W1 features: tx_frequency={wallet_features['tx_frequency']}, volume={wallet_features['total_volume']}")

print("\nTesting Wallet Classifier...")
classifier = WalletClassifier(features)
classification = classifier.classify('W1', events)
print(f"  W1: {classification['wallet_type']} (confidence={classification['confidence']})")

print("\nAll intelligence module tests passed!")
