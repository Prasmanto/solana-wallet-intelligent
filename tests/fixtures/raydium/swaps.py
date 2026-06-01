"""Golden test fixtures for Raydium protocol swaps."""

RAYDIUM_FIXTURES = [
    # ── Fixture 1: USDC -> Token swap ───────────────────────
    {
        "id": "raydium_usdc_to_token_001",
        "description": "Swap: 50 USDC -> 250 TOKEN on Raydium AMM",
        "input": {
            "signature": "5KtPnRayUsdcToToken11111111111111111111111111111",
            "slot": 225000101,
            "timestamp": 1714000200,
            "type": "SWAP",
            "source": "RAYDIUM",
            "fee": 5000,
            "fee_payer": "Wallet44444444444444444444444444444444444444",
            "description": "Swap 50 USDC for 250 TOKEN on Raydium",
            "accountData": [],
            "tokenTransfers": [
                {
                    "from_user_account": "Wallet44444444444444444444444444444444444444",
                    "to_user_account": "RaydiumAMM44444444444444444444444444444444",
                    "token_amount": 50.0,
                    "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                    "token_standard": "spl",
                },
                {
                    "from_user_account": "RaydiumAMM44444444444444444444444444444444",
                    "to_user_account": "Wallet44444444444444444444444444444444444444",
                    "token_amount": 250.0,
                    "mint": "TokenMint44444444444444444444444444444444444",
                    "token_standard": "spl",
                },
            ],
            "nativeTransfers": [],
            "events": {},
        },
        "expected": {
            "wallet": "Wallet44444444444444444444444444444444444444",
            "direction": "buy",  # Wallet pays USDC (base), receives TOKEN → buying TOKEN
            "protocol": "raydium",
            "token_in": {
                "mint": "TokenMint44444444444444444444444444444444444",
                "amount": "250.0",
                "decimals": 9,
            },
            "token_out": {
                "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "amount": "50.0",
                "decimals": 6,
            },
            "fee_sol": "0.000005",
        },
    },
    # ── Fixture 2: SOL -> Token swap ────────────────────────
    {
        "id": "raydium_sol_to_token_002",
        "description": "Swap: 2 SOL -> 1000 TOKEN on Raydium",
        "input": {
            "signature": "5KtPnRaySolToToken22222222222222222222222222222222",
            "slot": 225000102,
            "timestamp": 1714000260,
            "type": "SWAP",
            "source": "RAYDIUM",
            "fee": 5000,
            "fee_payer": "Wallet55555555555555555555555555555555555555",
            "description": "Swap 2 SOL for 1000 TOKEN on Raydium",
            "accountData": [],
            "tokenTransfers": [
                {
                    "from_user_account": "Wallet55555555555555555555555555555555555555",
                    "to_user_account": "RaydiumAMM55555555555555555555555555555555",
                    "token_amount": 2.0,
                    "mint": "So11111111111111111111111111111111111111112",
                    "token_standard": "native",
                },
                {
                    "from_user_account": "RaydiumAMM55555555555555555555555555555555",
                    "to_user_account": "Wallet55555555555555555555555555555555555555",
                    "token_amount": 1000.0,
                    "mint": "TokenMint55555555555555555555555555555555555",
                    "token_standard": "spl",
                },
            ],
            "nativeTransfers": [],
            "events": {},
        },
        "expected": {
            "wallet": "Wallet55555555555555555555555555555555555555",
            "direction": "buy",
            "protocol": "raydium",
            "token_in": {
                "mint": "TokenMint55555555555555555555555555555555555",
                "amount": "1000.0",
                "decimals": 9,
            },
            "token_out": {
                "mint": "So11111111111111111111111111111111111111112",
                "amount": "2.0",
                "decimals": 9,
            },
            "fee_sol": "0.000005",
        },
    },
]
