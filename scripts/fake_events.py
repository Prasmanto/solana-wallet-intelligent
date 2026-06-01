"""Fake event generator — produces realistic Solana-like test events.

Generates synthetic transaction data that mimics real Solana events:
- Token transfers (SOL, SPL tokens)
- Swap transactions (Raydium, Jupiter, Orca)
- Varies wallet addresses, amounts, programs

Usage:
    python -m scripts.fake_events --count 10
    python -m scripts.fake_events --count 50 --fail-rate 0.2
"""

from __future__ import annotations

import json
import random
import string
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ── Fake Data Generators ────────────────────────────────────

PROGRAMS = [
    "11111111111111111111111111111111",  # System Program
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",  # Token Program
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium AMM
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",  # Jupiter
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",  # Orca Whirlpool
    "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbooPZbYbOdDeD",  # Serum DEX
]

WALLET_LABELS = [
    "whale_main",
    "defi_trader",
    "nft_collector",
    "mev_bot",
    "yield_farmer",
    "arbitrage_bot",
    "smart_money",
    "retail_user",
]


def _random_address(length: int = 44) -> str:
    """Generate a fake base58-like Solana address."""
    chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    return "".join(random.choices(chars, k=length))


def _random_signature(length: int = 88) -> str:
    """Generate a fake transaction signature."""
    chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    return "".join(random.choices(chars, k=length))


def _random_sol_amount() -> float:
    """Generate a realistic SOL amount (whale dumps are rare)."""
    r = random.random()
    if r < 0.6:
        return round(random.uniform(0.01, 10.0), 6)  # Small
    elif r < 0.9:
        return round(random.uniform(10.0, 1000.0), 6)  # Medium
    else:
        return round(random.uniform(1000.0, 50000.0), 6)  # Whale


def _random_token_mint() -> str:
    """Generate a fake SPL token mint address."""
    return _random_address(44)


@dataclass
class FakeTransaction:
    """Represents a synthetic Solana transaction."""

    signature: str = field(default_factory=_random_signature)
    slot: int = field(default_factory=lambda: random.randint(200_000_000, 300_000_000))
    block_time: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    from_wallet: str = field(default_factory=_random_address)
    to_wallet: str = field(default_factory=_random_address)
    amount_sol: float = field(default_factory=_random_sol_amount)
    mint: str = field(default_factory=_random_token_mint)
    program_id: str = field(default_factory=lambda: random.choice(PROGRAMS))
    tx_type: str = field(default_factory=lambda: random.choice([
        "transfer", "swap", "transfer", "swap", "mint", "burn",
    ]))
    status: str = field(default_factory=lambda: random.choice([
        "success", "success", "success", "success", "error",
    ]))

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "signature": self.signature,
            "slot": self.slot,
            "block_time": self.block_time,
            "from_wallet": self.from_wallet,
            "to_wallet": self.to_wallet,
            "amount_sol": self.amount_sol,
            "mint": self.mint,
            "program_id": self.program_id,
            "tx_type": self.tx_type,
            "status": self.status,
        }


def generate_fake_events(
    count: int = 10,
    include_failures: bool = False,
    failure_rate: float = 0.2,
) -> list[dict[str, Any]]:
    """Generate a batch of fake transaction events.

    Args:
        count: Number of events to generate.
        include_failures: If True, some events will have status="error".
        failure_rate: Probability of generating a failed event.

    Returns:
        List of fake transaction dicts.
    """
    events = []
    for _ in range(count):
        tx = FakeTransaction()
        if include_failures and random.random() < failure_rate:
            tx.status = "error"
        events.append(tx.to_dict())
    return events


def generate_wallet_batch(
    wallet_count: int = 5,
    events_per_wallet: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    """Generate events grouped by wallet address.

    Useful for testing wallet-level analytics.
    """
    wallets = {}
    for _ in range(wallet_count):
        addr = _random_address()
        wallets[addr] = []
        for _ in range(events_per_wallet):
            tx = FakeTransaction(from_wallet=addr)
            wallets[addr].append(tx.to_dict())
    return wallets


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate fake Solana events")
    parser.add_argument("--count", type=int, default=10, help="Number of events")
    parser.add_argument("--fail-rate", type=float, default=0.0, help="Failure rate (0-1)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    events = generate_fake_events(
        count=args.count,
        include_failures=args.fail_rate > 0,
        failure_rate=args.fail_rate,
    )

    if args.json:
        print(json.dumps(events, indent=2))
    else:
        print(f"Generated {len(events)} events:")
        for i, e in enumerate(events, 1):
            status_icon = "OK" if e["status"] == "success" else "FAIL"
            print(
                f"  {i}. [{status_icon:>4}] {e['tx_type']:<8} "
                f"{e['amount_sol']:>12.6f} SOL  "
                f"{e['signature'][:16]}..."
            )
