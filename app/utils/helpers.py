"""Utils module - shared helpers and constants."""

from __future__ import annotations

SOLANA_LAMPORTS_PER_SOL = 1_000_000_000
SOLANA_MAX_ADDRESS_LENGTH = 44


def lamports_to_sol(lamports: int) -> float:
    """Convert lamports to SOL."""
    return lamports / SOLANA_LAMPORTS_PER_SOL


def sol_to_lamports(sol: float) -> int:
    """Convert SOL to lamports."""
    return int(sol * SOLANA_LAMPORTS_PER_SOL)


def is_valid_solana_address(address: str) -> bool:
    """Validate a Solana base58 address."""
    if not (32 <= len(address) <= SOLANA_MAX_ADDRESS_LENGTH):
        return False
    valid_chars = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
    return all(c in valid_chars for c in address)
