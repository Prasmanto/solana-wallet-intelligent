"""Persistent wallet graph builder — maintains adjacency list with weighted edges.

Production features:
- Load graph from DB on startup
- Update DB on every event
- Incremental updates (no full rebuild)
- Edge weight decay over time
- Never rely on in-memory only graph
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import structlog

from app.intelligence.time_decay import TimeDecayEngine

logger = structlog.get_logger(__name__)

# Edge weight constants
EDGE_WEIGHTS = {
    "TRANSFER": 1.0,
    "SWAP": 2.0,
    "BUY": 1.5,
    "SELL": 1.5,
}

# Decay factor for repeated interactions
REPEAT_DECAY = 0.9


class PersistentWalletGraph:
    """Persistent wallet graph with DB-backed storage.

    Production features:
    - Load from DB on startup
    - Update DB on every event
    - Incremental updates (no full rebuild)
    - Time-decay for edge weights
    - Memory-efficient with DB as source of truth
    """

    def __init__(
        self,
        repo: Any,
        decay_factor: float = REPEAT_DECAY,
        time_decay_factor: float = 0.01,
    ) -> None:
        self._repo = repo
        self._decay_factor = decay_factor
        self._time_decay = TimeDecayEngine(time_decay_factor)
        self._adjacency: dict[str, dict[str, float]] = {}
        self._node_cache: dict[str, dict[str, Any]] = {}
        self._loaded = False

    async def load(self) -> None:
        """Load graph from DB on startup."""
        if self._loaded:
            return

        logger.info("graph.loading", stage="startup")

        # Load nodes
        nodes = await self._repo.get_all_nodes()
        for node in nodes:
            self._node_cache[node["wallet_address"]] = node

        # Load edges
        edges = await self._repo.get_all_edges()
        for edge in edges:
            from_w = edge["from_wallet"]
            to_w = edge["to_wallet"]
            weight = edge.get("decay_weight", edge.get("weight", 0.0))

            if from_w not in self._adjacency:
                self._adjacency[from_w] = {}
            self._adjacency[from_w][to_w] = weight

        self._loaded = True
        logger.info(
            "graph.loaded",
            nodes=len(self._node_cache),
            edges=len(edges),
            stage="startup",
        )

    async def update(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Incrementally update graph with new event.

        Persists to DB and updates in-memory cache.
        """
        if not self._loaded:
            await self.load()

        wallet = event.get("wallet", "")
        if not wallet:
            return None

        # Extract counterparty
        counterparty = self._extract_counterparty(event)
        if not counterparty or counterparty == wallet:
            return None

        # Calculate edge weight
        event_type = event.get("event_type", "TRANSFER")
        base_weight = EDGE_WEIGHTS.get(event_type, 1.0)

        # Apply time decay to existing weight
        existing_weight = self._adjacency.get(wallet, {}).get(counterparty, 0.0)
        now = datetime.now(timezone.utc)
        decayed_weight = self._time_decay.calculate_decayed_weight(existing_weight, now)

        # Calculate new weight with decay
        new_weight = decayed_weight + base_weight

        # Update in-memory
        if wallet not in self._adjacency:
            self._adjacency[wallet] = {}
        self._adjacency[wallet][counterparty] = new_weight

        if counterparty not in self._adjacency:
            self._adjacency[counterparty] = {}
        self._adjacency[counterparty][wallet] = new_weight

        # Persist to DB
        try:
            await self._repo.upsert_node(wallet, {
                "interaction_count": self._node_cache.get(wallet, {}).get("interaction_count", 0) + 1,
                "last_seen": now,
            })

            await self._repo.upsert_edge(
                from_wallet=wallet,
                to_wallet=counterparty,
                edge_type=event_type,
                weight=new_weight,
                decay_weight=decayed_weight,
                last_interaction=now,
            )
        except Exception as e:
            logger.error(
                "graph.persist_error",
                wallet=wallet[:16],
                error=str(e),
                stage="persistence",
            )

        return {
            "wallet": wallet,
            "counterparty": counterparty,
            "weight": new_weight,
            "edge_type": event_type,
        }

    def _extract_counterparty(self, event: dict[str, Any]) -> str:
        """Extract counterparty wallet from event."""
        data = event.get("data", {})
        if data.get("to"):
            return str(data["to"])
        if data.get("to_wallet"):
            return str(data["to_wallet"])
        if data.get("counterparty"):
            return str(data["counterparty"])
        return ""

    def get_neighbors(self, wallet: str) -> dict[str, float]:
        """Get all neighbors of a wallet with edge weights."""
        return dict(self._adjacency.get(wallet, {}))

    def get_node_count(self) -> int:
        """Get total number of nodes."""
        return len(self._node_cache)

    def get_edge_count(self) -> int:
        """Get total number of unique edges."""
        count = 0
        for neighbors in self._adjacency.values():
            count += len(neighbors)
        return count // 2  # Undirected graph

    def export_adjacency(self) -> dict[str, dict[str, float]]:
        """Export adjacency list."""
        return {k: dict(v) for k, v in self._adjacency.items()}
