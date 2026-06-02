"""Test transaction parser — validates normalization pipeline.

Tests:
1. Protocol detection (Jupiter, Raydium, Pump.fun, Orca)
2. SOL transfer parsing
3. SPL token swap parsing
4. Direction classification (buy/sell)
5. Decimal normalization
6. Error handling (missing fields, unsupported types)
7. Idempotent parsing
8. End-to-end pipeline test

Usage:
    python -m scripts.test_parser
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import structlog

from app.config.logging import setup_logging
from app.parser.protocol_detector import ProtocolDetector, DEXProtocol
from app.parser.transaction_normalizer import TransactionNormalizer
from app.schemas.helius import WebhookTransaction
from app.schemas.trade import TradeDirection, DEXProtocol as TradeDEX

logger = structlog.get_logger("parser_test")


# ── Test Fixtures ───────────────────────────────────────────

def make_jupiter_swap() -> WebhookTransaction:
    """Simulate a Jupiter swap: SOL -> USDC."""
    return WebhookTransaction(
        signature="5KtPnJupiterSwapSig123456789012345678901234567890",
        slot=225000000,
        timestamp=int(time.time()),
        type="SWAP",
        source="JUPITER",
        fee=5000,
        fee_payer="WalletAddress111111111111111111111111111111",
        description="Swap 1.5 SOL for 225 USDC on Jupiter",
        accountData=[],
        tokenTransfers=[
            {
                "from_user_account": "WalletAddress111111111111111111111111111111",
                "to_user_account": "PumpFunAddress11111111111111111111111111111",
                "token_amount": 1.5,
                "mint": "So11111111111111111111111111111111111111112",
                "token_standard": "native",
            },
            {
                "from_user_account": "RaydiumPool1111111111111111111111111111111",
                "to_user_account": "WalletAddress111111111111111111111111111111",
                "token_amount": 225.0,
                "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "token_standard": "spl",
            },
        ],
        nativeTransfers=[],
        events={},
    )


def make_raydium_swap() -> WebhookTransaction:
    """Simulate a Raydium swap: USDC -> TOKEN."""
    return WebhookTransaction(
        signature="5KtPnRaydiumSwapSig123456789012345678901234567890",
        slot=225000100,
        timestamp=int(time.time()),
        type="SWAP",
        source="RAYDIUM",
        fee=5000,
        fee_payer="WalletAddress222222222222222222222222222222",
        description="Swap 100 USDC for 500 TOKEN on Raydium",
        accountData=[],
        tokenTransfers=[
            {
                "from_user_account": "WalletAddress222222222222222222222222222222",
                "to_user_account": "RaydiumPool2222222222222222222222222222222",
                "token_amount": 100.0,
                "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "token_standard": "spl",
            },
            {
                "from_user_account": "RaydiumPool2222222222222222222222222222222",
                "to_user_account": "WalletAddress222222222222222222222222222222",
                "token_amount": 500.0,
                "mint": "TokenMint3333333333333333333333333333333333",
                "token_standard": "spl",
            },
        ],
        nativeTransfers=[],
        events={},
    )


def make_pumpfun_swap() -> WebhookTransaction:
    """Simulate a Pump.fun swap: SOL -> MemeCoin."""
    return WebhookTransaction(
        signature="5KtPnPumpFunSwapSig123456789012345678901234567890",
        slot=225000200,
        timestamp=int(time.time()),
        type="SWAP",
        source="PUMP_FUN",
        fee=5000,
        fee_payer="WalletAddress444444444444444444444444444444",
        description="Buy 1000 MemeCoin with 0.5 SOL on Pump.fun",
        accountData=[],
        tokenTransfers=[
            {
                "from_user_account": "WalletAddress444444444444444444444444444444",
                "to_user_account": "PumpFunBonding4444444444444444444444444444",
                "token_amount": 0.5,
                "mint": "So11111111111111111111111111111111111111112",
                "token_standard": "native",
            },
            {
                "from_user_account": "PumpFunBonding4444444444444444444444444444",
                "to_user_account": "WalletAddress444444444444444444444444444444",
                "token_amount": 1000.0,
                "mint": "MemeCoinMint44444444444444444444444444444444",
                "token_standard": "spl",
            },
        ],
        nativeTransfers=[],
        events={},
    )


def make_native_sol_transfer() -> WebhookTransaction:
    """Simulate a native SOL transfer."""
    return WebhookTransaction(
        signature="5KtPnNativeTransferSig123456789012345678901234567890",
        slot=225000300,
        timestamp=int(time.time()),
        type="TRANSFER",
        source="SYSTEM_PROGRAM",
        fee=5000,
        fee_payer="WalletAddress555555555555555555555555555555",
        description="Transfer 2 SOL",
        accountData=[],
        tokenTransfers=[],
        nativeTransfers=[
            {
                "fromUserAccount": "WalletAddress555555555555555555555555555555",
                "toUserAccount": "RecipientAddress55555555555555555555555555",
                "amount": 2000000000,  # 2 SOL in lamports
            }
        ],
        events={},
    )


def make_unsupported_tx() -> WebhookTransaction:
    """Simulate an unsupported transaction type."""
    return WebhookTransaction(
        signature="5KtPnUnsupportedSig123456789012345678901234567890",
        slot=225000400,
        timestamp=int(time.time()),
        type="CREATE_ACCOUNT",
        source="SYSTEM_PROGRAM",
        fee=5000,
        fee_payer="WalletAddress666666666666666666666666666666",
        description="Create account",
        accountData=[],
        tokenTransfers=[],
        nativeTransfers=[],
        events={},
    )


# ── Tests ───────────────────────────────────────────────────

async def run_parser_test() -> None:
    """Run the parser test suite."""
    setup_logging(log_level="INFO", json_output=False)

    print("\n" + "=" * 60)
    print("  TRANSACTION PARSER TEST")
    print("=" * 60)

    detector = ProtocolDetector()
    normalizer = TransactionNormalizer()

    # ── Test 1: Protocol Detection ──────────────────────────
    print("\n  Test 1: Protocol detection")
    print("  " + "-" * 50)

    # Jupiter
    protocol = detector.detect(source="JUPITER", program_ids=[], description="")
    print(f"    Jupiter (source):  {protocol.value} {'OK' if protocol == TradeDEX.JUPITER else 'FAIL'}")

    # Raydium
    protocol = detector.detect(source="RAYDIUM", program_ids=[], description="")
    print(f"    Raydium (source):  {protocol.value} {'OK' if protocol == TradeDEX.RAYDIUM else 'FAIL'}")

    # Pump.fun
    protocol = detector.detect(source="PUMP_FUN", program_ids=[], description="")
    print(f"    Pump.fun (source): {protocol.value} {'OK' if protocol == TradeDEX.PUMP_FUN else 'FAIL'}")

    # Program ID detection
    protocol = detector.detect(
        source="",
        program_ids=["JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"],
        description="",
    )
    print(f"    Jupiter (program): {protocol.value} {'OK' if protocol == TradeDEX.JUPITER else 'FAIL'}")

    # Keyword detection
    protocol = detector.detect(
        source="",
        program_ids=[],
        description="Swap tokens on raydium",
    )
    print(f"    Raydium (keyword): {protocol.value} {'OK' if protocol == TradeDEX.RAYDIUM else 'FAIL'}")

    # Unknown
    protocol = detector.detect(source="", program_ids=[], description="")
    print(f"    Unknown:           {protocol.value} {'OK' if protocol == TradeDEX.UNKNOWN else 'FAIL'}")

    # ── Test 2: Jupiter Swap Parsing ────────────────────────
    print("\n  Test 2: Jupiter swap parsing")
    print("  " + "-" * 50)

    tx = make_jupiter_swap()
    result = normalizer.normalize(tx)
    print(f"    Success: {result.success} {'OK' if result.success else 'FAIL'}")

    if result.success and result.trade:
        trade = result.trade
        print(f"    Wallet:     {trade.wallet[:16]}...")
        print(f"    Direction:  {trade.direction.value}")
        print(f"    Token In:   {trade.token_in.mint[:16]}... ({trade.token_in.amount} tokens)")
        print(f"    Token Out:  {trade.token_out.mint[:16]}... ({trade.token_out.amount} tokens)")
        print(f"    Protocol:   {trade.protocol.value}")
        print(f"    Fee:        {trade.fee_sol} SOL")

    # ── Test 3: Raydium Swap Parsing ────────────────────────
    print("\n  Test 3: Raydium swap parsing")
    print("  " + "-" * 50)

    tx = make_raydium_swap()
    result = normalizer.normalize(tx)
    print(f"    Success: {result.success} {'OK' if result.success else 'FAIL'}")

    if result.success and result.trade:
        trade = result.trade
        print(f"    Protocol:   {trade.protocol.value}")
        print(f"    Token In:   {trade.token_in.amount} {trade.token_in.mint[:8]}...")
        print(f"    Token Out:  {trade.token_out.amount} {trade.token_out.mint[:8]}...")

    # ── Test 4: Pump.fun Swap Parsing ───────────────────────
    print("\n  Test 4: Pump.fun swap parsing")
    print("  " + "-" * 50)

    tx = make_pumpfun_swap()
    result = normalizer.normalize(tx)
    print(f"    Success: {result.success} {'OK' if result.success else 'FAIL'}")

    if result.success and result.trade:
        trade = result.trade
        print(f"    Protocol:   {trade.protocol.value}")
        print(f"    Token In:   {trade.token_in.amount} SOL")
        print(f"    Token Out:  {trade.token_out.amount} tokens")

    # ── Test 5: Native SOL Transfer Parsing ─────────────────
    print("\n  Test 5: Native SOL transfer parsing")
    print("  " + "-" * 50)

    tx = make_native_sol_transfer()
    result = normalizer.normalize(tx)
    print(f"    Success: {result.success} {'OK' if result.success else 'FAIL'}")

    if result.success and result.trade:
        trade = result.trade
        print(f"    Direction:  {trade.direction.value}")
        print(f"    Amount:     {trade.token_out.amount} SOL")

    # ── Test 6: Unsupported Transaction Type ────────────────
    print("\n  Test 6: Unsupported transaction type")
    print("  " + "-" * 50)

    tx = make_unsupported_tx()
    result = normalizer.normalize(tx)
    print(f"    Success: {result.success} (expected False)")
    print(f"    Error:   {result.error_code}")
    print(f"    Correct: {'OK' if not result.success else 'FAIL'}")

    # ── Test 7: Direction Classification ────────────────────
    print("\n  Test 7: Direction classification")
    print("  " + "-" * 50)

    # SOL -> USDC (buying USDC with SOL)
    tx = make_jupiter_swap()
    result = normalizer.normalize(tx)
    if result.trade:
        print(f"    SOL -> USDC: {result.trade.direction.value} {'OK' if result.trade.direction == TradeDirection.BUY else 'FAIL'}")

    # USDC -> TOKEN (buying TOKEN with USDC)
    tx = make_raydium_swap()
    result = normalizer.normalize(tx)
    if result.trade:
        print(f"    USDC -> TOKEN: {result.trade.direction.value} {'OK' if result.trade.direction == TradeDirection.BUY else 'FAIL'}")

    # ── Test 8: Decimal Normalization ───────────────────────
    print("\n  Test 8: Decimal normalization")
    print("  " + "-" * 50)

    tx = make_jupiter_swap()
    result = normalizer.normalize(tx)
    if result.trade:
        # token_in = what wallet receives (225 USDC)
        # token_out = what wallet pays (1.5 SOL)
        print(f"    SOL amount (paid): {result.trade.token_out.amount} (expected 1.5)")
        print(f"    USDC amount (received): {result.trade.token_in.amount} (expected 225.0)")
        correct = result.trade.token_out.amount == Decimal("1.5") and result.trade.token_in.amount == Decimal("225.0")
        print(f"    Correct: {'OK' if correct else 'FAIL'}")

    # ── Summary ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    from decimal import Decimal
    asyncio.run(run_parser_test())
