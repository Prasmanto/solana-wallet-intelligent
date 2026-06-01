"""Golden test fixtures for Jupiter protocol swaps.

Each fixture contains:
- input: Helius WebhookTransaction data
- expected: NormalizedTrade expected output
- description: Human-readable test description
"""

JUPITER_FIXTURES = [
    # ── Fixture 1: Simple SOL -> USDC swap ──────────────────
    {
        "id": "jupiter_sol_to_usdc_001",
        "description": "Simple swap: 1.5 SOL -> 225 USDC on Jupiter",
        "input": {
            "signature": "5KtPnJupSolToUsdc11111111111111111111111111111111",
            "slot": 225000001,
            "timestamp": 1714000000,
            "type": "SWAP",
            "source": "JUPITER",
            "fee": 5000,
            "fee_payer": "Wallet11111111111111111111111111111111111111",
            "description": "Swap 1.5 SOL for 225 USDC on Jupiter",
            "accountData": [],
            "tokenTransfers": [
                {
                    "from_user_account": "Wallet11111111111111111111111111111111111111",
                    "to_user_account": "JupSwapPool11111111111111111111111111111111",
                    "token_amount": 1.5,
                    "mint": "So11111111111111111111111111111111111111112",
                    "token_standard": "native",
                },
                {
                    "from_user_account": "JupSwapPool11111111111111111111111111111111",
                    "to_user_account": "Wallet11111111111111111111111111111111111111",
                    "token_amount": 225.0,
                    "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                    "token_standard": "spl",
                },
            ],
            "nativeTransfers": [],
            "events": {},
        },
        "expected": {
            "wallet": "Wallet11111111111111111111111111111111111111",
            "direction": "buy",
            "protocol": "jupiter",
            "token_in": {
                "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "amount": "225.0",
                "decimals": 6,
            },
            "token_out": {
                "mint": "So11111111111111111111111111111111111111112",
                "amount": "1.5",
                "decimals": 9,
            },
            "fee_sol": "0.000005",
        },
    },
    # ── Fixture 2: USDC -> SOL swap (selling) ───────────────
    {
        "id": "jupiter_usdc_to_sol_002",
        "description": "Swap: 100 USDC -> 0.67 SOL on Jupiter (sell)",
        "input": {
            "signature": "5KtPnJupUsdcToSol22222222222222222222222222222222",
            "slot": 225000002,
            "timestamp": 1714000060,
            "type": "SWAP",
            "source": "JUPITER",
            "fee": 5000,
            "fee_payer": "Wallet22222222222222222222222222222222222222",
            "description": "Swap 100 USDC for 0.67 SOL on Jupiter",
            "accountData": [],
            "tokenTransfers": [
                {
                    "from_user_account": "Wallet22222222222222222222222222222222222222",
                    "to_user_account": "JupSwapPool22222222222222222222222222222222",
                    "token_amount": 100.0,
                    "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                    "token_standard": "spl",
                },
                {
                    "from_user_account": "JupSwapPool22222222222222222222222222222222",
                    "to_user_account": "Wallet22222222222222222222222222222222222222",
                    "token_amount": 0.67,
                    "mint": "So11111111111111111111111111111111111111112",
                    "token_standard": "native",
                },
            ],
            "nativeTransfers": [],
            "events": {},
        },
        "expected": {
            "wallet": "Wallet22222222222222222222222222222222222222",
            "direction": "buy",  # Wallet pays USDC (base), receives SOL → buying SOL
            "protocol": "jupiter",
            "token_in": {
                "mint": "So11111111111111111111111111111111111111112",
                "amount": "0.67",
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
    # ── Fixture 3: Token -> Token swap ──────────────────────
    {
        "id": "jupiter_token_to_token_003",
        "description": "Swap: 100 USDC -> 500 BONK on Jupiter",
        "input": {
            "signature": "5KtPnJupTokenSwap33333333333333333333333333333333",
            "slot": 225000003,
            "timestamp": 1714000120,
            "type": "SWAP",
            "source": "JUPITER",
            "fee": 6000,
            "fee_payer": "Wallet33333333333333333333333333333333333333",
            "description": "Swap 100 USDC for 500 BONK on Jupiter",
            "accountData": [],
            "tokenTransfers": [
                {
                    "from_user_account": "Wallet33333333333333333333333333333333333333",
                    "to_user_account": "JupSwapPool33333333333333333333333333333333",
                    "token_amount": 100.0,
                    "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                    "token_standard": "spl",
                },
                {
                    "from_user_account": "JupSwapPool33333333333333333333333333333333",
                    "to_user_account": "Wallet33333333333333333333333333333333333333",
                    "token_amount": 500.0,
                    "mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
                    "token_standard": "spl",
                },
            ],
            "nativeTransfers": [],
            "events": {},
        },
        "expected": {
            "wallet": "Wallet33333333333333333333333333333333333333",
            "direction": "buy",  # Wallet pays USDC (base), receives BONK → buying BONK
            "protocol": "jupiter",
            "token_in": {
                "mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
                "amount": "500.0",
                "decimals": 9,
            },
            "token_out": {
                "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "amount": "100.0",
                "decimals": 6,
            },
            "fee_sol": "0.000006",
        },
    },
]
