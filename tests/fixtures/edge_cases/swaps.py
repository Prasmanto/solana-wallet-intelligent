"""Edge case fixtures for parser testing.

Tests wrapped SOL, failed transactions, multi-hop, and other edge cases.
"""

EDGE_CASE_FIXTURES = [
    # ── Edge 1: Wrapped SOL (WSOL) swap ─────────────────────
    {
        "id": "edge_wsol_swap_001",
        "description": "Swap using Wrapped SOL instead of native SOL",
        "input": {
            "signature": "5KtPnEdgeWsolSwap1111111111111111111111111111111",
            "slot": 225000301,
            "timestamp": 1714000400,
            "type": "SWAP",
            "source": "JUPITER",
            "fee": 5000,
            "fee_payer": "Wallet88888888888888888888888888888888888888",
            "description": "Swap WSOL for USDC",
            "accountData": [],
            "tokenTransfers": [
                {
                    "from_user_account": "Wallet88888888888888888888888888888888888888",
                    "to_user_account": "JupPool88888888888888888888888888888888888",
                    "token_amount": 1.0,
                    "mint": "So11111111111111111111111111111111111111112",
                    "token_standard": "spl",
                },
                {
                    "from_user_account": "JupPool88888888888888888888888888888888888",
                    "to_user_account": "Wallet88888888888888888888888888888888888888",
                    "token_amount": 150.0,
                    "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                    "token_standard": "spl",
                },
            ],
            "nativeTransfers": [],
            "events": {},
        },
        "expected": {
            "wallet": "Wallet88888888888888888888888888888888888888",
            "direction": "buy",
            "protocol": "jupiter",
            "token_in": {
                "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "amount": "150.0",
                "decimals": 6,
            },
            "token_out": {
                "mint": "So11111111111111111111111111111111111111112",
                "amount": "1.0",
                "decimals": 9,
            },
            "fee_sol": "0.000005",
        },
    },
    # ── Edge 2: Failed transaction (should be skipped) ──────
    {
        "id": "edge_failed_tx_002",
        "description": "Failed transaction with no signature",
        "input": {
            "signature": "",
            "slot": 225000302,
            "timestamp": 1714000460,
            "type": "SWAP",
            "source": "JUPITER",
            "fee": 0,
            "fee_payer": "",
            "description": "Failed swap",
            "accountData": [],
            "tokenTransfers": [],
            "nativeTransfers": [],
            "events": {},
        },
        "expected": None,  # Should fail
        "expected_error": "MISSING_SIGNATURE",
    },
    # ── Edge 3: Unknown protocol ────────────────────────────
    {
        "id": "edge_unknown_protocol_003",
        "description": "Swap on unknown DEX",
        "input": {
            "signature": "5KtPnEdgeUnknown11111111111111111111111111111111",
            "slot": 225000303,
            "timestamp": 1714000520,
            "type": "SWAP",
            "source": "UNKNOWN_DEX",
            "fee": 5000,
            "fee_payer": "Wallet99999999999999999999999999999999999999",
            "description": "Swap on some unknown DEX",
            "accountData": [],
            "tokenTransfers": [
                {
                    "from_user_account": "Wallet99999999999999999999999999999999999999",
                    "to_user_account": "UnknownPool9999999999999999999999999999999",
                    "token_amount": 100.0,
                    "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                    "token_standard": "spl",
                },
                {
                    "from_user_account": "UnknownPool9999999999999999999999999999999",
                    "to_user_account": "Wallet99999999999999999999999999999999999999",
                    "token_amount": 500.0,
                    "mint": "UnknownToken999999999999999999999999999999999",
                    "token_standard": "spl",
                },
            ],
            "nativeTransfers": [],
            "events": {},
        },
        "expected": {
            "wallet": "Wallet99999999999999999999999999999999999999",
            "direction": "buy",  # Wallet pays USDC (base), receives UNKNOWN → buying
            "protocol": "unknown",
            "token_in": {
                "mint": "UnknownToken999999999999999999999999999999999",
                "amount": "500.0",
                "decimals": 9,
            },
            "token_out": {
                "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "amount": "100.0",
                "decimals": 6,
            },
            "fee_sol": "0.000005",
        },
    },
    # ── Edge 4: Large decimal amounts ───────────────────────
    {
        "id": "edge_large_amount_004",
        "description": "Swap with very large token amount",
        "input": {
            "signature": "5KtPnEdgeLargeAmt1111111111111111111111111111111",
            "slot": 225000304,
            "timestamp": 1714000580,
            "type": "SWAP",
            "source": "RAYDIUM",
            "fee": 5000,
            "fee_payer": "WalletAAAA111111111111111111111111111111111",
            "description": "Swap 1000 USDC for 1000000000 SHIB",
            "accountData": [],
            "tokenTransfers": [
                {
                    "from_user_account": "WalletAAAA111111111111111111111111111111111",
                    "to_user_account": "RaydiumAAAA11111111111111111111111111111111",
                    "token_amount": 1000.0,
                    "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                    "token_standard": "spl",
                },
                {
                    "from_user_account": "RaydiumAAAA11111111111111111111111111111111",
                    "to_user_account": "WalletAAAA111111111111111111111111111111111",
                    "token_amount": 1000000000.0,
                    "mint": "SHIBTokenAAAA111111111111111111111111111111",
                    "token_standard": "spl",
                },
            ],
            "nativeTransfers": [],
            "events": {},
        },
        "expected": {
            "wallet": "WalletAAAA111111111111111111111111111111111",
            "direction": "buy",  # Wallet pays USDC (base), receives SHIB → buying SHIB
            "protocol": "raydium",
            "token_in": {
                "mint": "SHIBTokenAAAA111111111111111111111111111111",
                "amount": "1000000000.0",
                "decimals": 9,
            },
            "token_out": {
                "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "amount": "1000.0",
                "decimals": 6,
            },
            "fee_sol": "0.000005",
        },
    },
    # ── Edge 5: Native SOL transfer (not swap) ──────────────
    {
        "id": "edge_native_transfer_005",
        "description": "Simple SOL transfer (not a swap)",
        "input": {
            "signature": "5KtPnEdgeNativeXfer11111111111111111111111111111",
            "slot": 225000305,
            "timestamp": 1714000640,
            "type": "TRANSFER",
            "source": "SYSTEM_PROGRAM",
            "fee": 5000,
            "fee_payer": "WalletBBBB111111111111111111111111111111111",
            "description": "Transfer 5 SOL",
            "accountData": [],
            "tokenTransfers": [],
            "nativeTransfers": [
                {
                    "fromUserAccount": "WalletBBBB111111111111111111111111111111111",
                    "toUserAccount": "RecipientBBBB11111111111111111111111111111",
                    "amount": 5000000000,
                }
            ],
            "events": {},
        },
        "expected": {
            "wallet": "WalletBBBB111111111111111111111111111111111",
            "direction": "buy",
            "protocol": "unknown",
            "token_in": {
                "mint": "So11111111111111111111111111111111111111112",
                "amount": "5.0",
                "decimals": 9,
            },
            "token_out": {
                "mint": "So11111111111111111111111111111111111111112",
                "amount": "5.0",
                "decimals": 9,
            },
            "fee_sol": "0.000005",
        },
    },
]
