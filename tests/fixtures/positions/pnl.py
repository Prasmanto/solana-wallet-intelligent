"""Test fixtures for position tracking and PnL calculation.

Golden test cases for:
- FIFO lot accounting
- Realized PnL calculation
- Position lifecycle
- Edge cases (partial exits, scaling)
"""

from datetime import datetime, timezone
from decimal import Decimal

# ── Position Test Fixtures ──────────────────────────────────

POSITION_FIXTURES = [
    # ── Fixture 1: Simple buy then sell (profit) ────────────
    {
        "id": "position_buy_sell_profit_001",
        "description": "Buy 100 TOKEN at $1, sell 100 TOKEN at $2 = $100 profit",
        "trades": [
            {
                "trade_id": "trade_001",
                "signature": "sig_buy_001",
                "wallet": "Wallet11111111111111111111111111111111111111",
                "direction": "buy",
                "token_in_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
                "token_in_amount": "100.0",
                "token_out_mint": "TokenMint11111111111111111111111111111111",
                "token_out_amount": "100.0",
                "fee_sol": "0.000005",
                "timestamp": "2026-01-01T10:00:00Z",
            },
            {
                "trade_id": "trade_002",
                "signature": "sig_sell_001",
                "wallet": "Wallet11111111111111111111111111111111111111",
                "direction": "sell",
                "token_in_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
                "token_in_amount": "200.0",
                "token_out_mint": "TokenMint11111111111111111111111111111111",
                "token_out_amount": "100.0",
                "fee_sol": "0.000005",
                "timestamp": "2026-01-01T12:00:00Z",
            },
        ],
        "expected": {
            "position_size": "0",
            "realized_pnl": "100.0",
            "realized_roi": "100.0",
            "total_buys": 1,
            "total_sells": 1,
        },
    },
    # ── Fixture 2: Buy then partial sell ────────────────────
    {
        "id": "position_partial_sell_002",
        "description": "Buy 100 TOKEN at $1, sell 50 TOKEN at $2 = $50 profit",
        "trades": [
            {
                "trade_id": "trade_003",
                "signature": "sig_buy_002",
                "wallet": "Wallet22222222222222222222222222222222222222",
                "direction": "buy",
                "token_in_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "token_in_amount": "100.0",
                "token_out_mint": "TokenMint22222222222222222222222222222222",
                "token_out_amount": "100.0",
                "fee_sol": "0.000005",
                "timestamp": "2026-01-01T10:00:00Z",
            },
            {
                "trade_id": "trade_004",
                "signature": "sig_sell_002",
                "wallet": "Wallet22222222222222222222222222222222222222",
                "direction": "sell",
                "token_in_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "token_in_amount": "100.0",
                "token_out_mint": "TokenMint22222222222222222222222222222222",
                "token_out_amount": "50.0",
                "fee_sol": "0.000005",
                "timestamp": "2026-01-01T12:00:00Z",
            },
        ],
        "expected": {
            "position_size": "50.0",
            "realized_pnl": "50.0",
            "realized_roi": "50.0",
            "total_buys": 1,
            "total_sells": 1,
        },
    },
    # ── Fixture 3: Scaling in (multiple buys) ───────────────
    {
        "id": "position_scaling_in_003",
        "description": "Buy 50 at $1, buy 50 at $2, sell 100 at $2 = $25 profit",
        "trades": [
            {
                "trade_id": "trade_005",
                "signature": "sig_buy_003",
                "wallet": "Wallet33333333333333333333333333333333333333",
                "direction": "buy",
                "token_in_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "token_in_amount": "50.0",
                "token_out_mint": "TokenMint33333333333333333333333333333333",
                "token_out_amount": "50.0",
                "fee_sol": "0.000005",
                "timestamp": "2026-01-01T10:00:00Z",
            },
            {
                "trade_id": "trade_006",
                "signature": "sig_buy_004",
                "wallet": "Wallet33333333333333333333333333333333333333",
                "direction": "buy",
                "token_in_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "token_in_amount": "100.0",
                "token_out_mint": "TokenMint33333333333333333333333333333333",
                "token_out_amount": "50.0",
                "fee_sol": "0.000005",
                "timestamp": "2026-01-01T11:00:00Z",
            },
            {
                "trade_id": "trade_007",
                "signature": "sig_sell_003",
                "wallet": "Wallet33333333333333333333333333333333333333",
                "direction": "sell",
                "token_in_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "token_in_amount": "200.0",
                "token_out_mint": "TokenMint33333333333333333333333333333333",
                "token_out_amount": "100.0",
                "fee_sol": "0.000005",
                "timestamp": "2026-01-01T12:00:00Z",
            },
        ],
        "expected": {
            "position_size": "0",
            "realized_pnl": "25.0",
            "realized_roi": "16.67",
            "total_buys": 2,
            "total_sells": 1,
        },
    },
    # ── Fixture 4: Sell at loss ─────────────────────────────
    {
        "id": "position_sell_loss_004",
        "description": "Buy 100 TOKEN at $2, sell 100 TOKEN at $1 = -$100 loss",
        "trades": [
            {
                "trade_id": "trade_008",
                "signature": "sig_buy_005",
                "wallet": "Wallet44444444444444444444444444444444444444",
                "direction": "buy",
                "token_in_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "token_in_amount": "200.0",
                "token_out_mint": "TokenMint44444444444444444444444444444444",
                "token_out_amount": "100.0",
                "fee_sol": "0.000005",
                "timestamp": "2026-01-01T10:00:00Z",
            },
            {
                "trade_id": "trade_009",
                "signature": "sig_sell_004",
                "wallet": "Wallet44444444444444444444444444444444444444",
                "direction": "sell",
                "token_in_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "token_in_amount": "100.0",
                "token_out_mint": "TokenMint44444444444444444444444444444444",
                "token_out_amount": "100.0",
                "fee_sol": "0.000005",
                "timestamp": "2026-01-01T12:00:00Z",
            },
        ],
        "expected": {
            "position_size": "0",
            "realized_pnl": "-100.0",
            "realized_roi": "-50.0",
            "total_buys": 1,
            "total_sells": 1,
        },
    },
]
