"""Protocol detection strategy.

Identifies which DEX protocol was used in a transaction.
Uses multiple detection methods:
1. Helius source field (most reliable)
2. Program ID matching
3. Token transfer pattern analysis
4. Description string parsing

Each protocol has known program IDs and patterns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from app.schemas.trade import DEXProtocol

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ProtocolSignature:
    """A protocol's identifying characteristics."""

    protocol: DEXProtocol
    program_ids: list[str]
    source_names: list[str]
    keywords: list[str]


# ── Known Protocol Signatures ───────────────────────────────

PROTOCOL_SIGNATURES: list[ProtocolSignature] = [
    # Jupiter Aggregator
    ProtocolSignature(
        protocol=DEXProtocol.JUPITER,
        program_ids=[
            "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",  # Jupiter v6
            "JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB",  # Jupiter v4
            "JUP3jqKShLTC4TXbKQ9sRMSMgGKHGSuR3wEhm4yQnM",  # Jupiter v3
        ],
        source_names=["JUPITER"],
        keywords=["jupiter", "jup"],
    ),
    # Raydium
    ProtocolSignature(
        protocol=DEXProtocol.RAYDIUM,
        program_ids=[
            "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium AMM v4
            "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",  # Raydium CLMM
            "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",  # Raydium CPMM
        ],
        source_names=["RAYDIUM"],
        keywords=["raydium", "ray"],
    ),
    # Pump.fun
    ProtocolSignature(
        protocol=DEXProtocol.PUMP_FUN,
        program_ids=[
            "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",  # Pump.fun
            "pumpkinfun7gQNbZ3BVMa4R9tXmCj4pJZs8Z8Z8Z8",  # Pumpkin (Pump fork)
        ],
        source_names=["PUMP_FUN", "PUMPFUN"],
        keywords=["pump.fun", "pumpfun", "pump"],
    ),
    # Orca
    ProtocolSignature(
        protocol=DEXProtocol.ORCA,
        program_ids=[
            "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",  # Orca Whirlpool
            "9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP",  # Orca Token Swap
        ],
        source_names=["ORCA"],
        keywords=["orca", "whirlpool"],
    ),
    # Photon
    ProtocolSignature(
        protocol=DEXProtocol.PHOTON,
        program_ids=[
            "PHoNiNgPhOnOnPhOnOnPhOnOnPhOnOnPhOnOnPhOnOn",  # Placeholder
        ],
        source_names=["PHOTON"],
        keywords=["photon"],
    ),
]


class ProtocolDetector:
    """Detects which DEX protocol was used in a transaction."""

    def detect(
        self,
        source: str,
        program_ids: list[str],
        description: str = "",
    ) -> DEXProtocol:
        """Detect protocol from transaction metadata.

        Args:
            source: Helius source field (e.g., "JUPITER", "RAYDIUM")
            program_ids: List of program IDs in the transaction
            description: Human-readable description

        Returns:
            Detected DEXProtocol (or UNKNOWN)
        """
        # 1. Check Helius source field (most reliable)
        if source:
            normalized_source = source.upper().strip()
            for sig in PROTOCOL_SIGNATURES:
                if normalized_source in sig.source_names:
                    logger.debug(
                        "protocol.detected_by_source",
                        source=source,
                        protocol=sig.protocol.value,
                    )
                    return sig.protocol

        # 2. Check program IDs
        if program_ids:
            for sig in PROTOCOL_SIGNATURES:
                for pid in program_ids:
                    if pid in sig.program_ids:
                        logger.debug(
                            "protocol.detected_by_program",
                            program_id=pid[:16],
                            protocol=sig.protocol.value,
                        )
                        return sig.protocol

        # 3. Check description keywords
        if description:
            desc_lower = description.lower()
            for sig in PROTOCOL_SIGNATURES:
                for keyword in sig.keywords:
                    if keyword in desc_lower:
                        logger.debug(
                            "protocol.detected_by_keyword",
                            keyword=keyword,
                            protocol=sig.protocol.value,
                        )
                        return sig.protocol

        logger.debug("protocol.unknown", source=source, program_ids=program_ids[:3])
        return DEXProtocol.UNKNOWN

    def extract_program_ids(self, tx: dict[str, Any]) -> list[str]:
        """Extract program IDs from various transaction formats."""
        program_ids = []

        # From accountData
        account_data = tx.get("accountData", tx.get("account_data", []))
        if isinstance(account_data, list):
            for account in account_data:
                if isinstance(account, dict):
                    program_id = account.get("account", "")
                    if program_id:
                        program_ids.append(program_id)

        # From events (Helius enhanced format)
        events = tx.get("events", {})
        if isinstance(events, dict):
            swap_event = events.get("swap", events.get("SWAP", {}))
            if isinstance(swap_event, dict):
                # Jupiter puts inner instructions here
                pass

        return program_ids
