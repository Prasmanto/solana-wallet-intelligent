"""Golden test fixtures for Pump.fun protocol swaps."""

PUMPFUN_FIXTURES = [
    # ── Fixture 1: Buy meme coin with SOL ───────────────────
    {
        "id": "pumpfun_buy_meme_001",
        "description": "Buy: 1 SOL -> 5000 MEME on Pump.fun bonding curve",
        "input": {
            "signature": "5KtPnPumpBuyMeme11111111111111111111111111111111",
            "slot": 225000201,
            "timestamp": 1714000300,
            "type": "SWAP",
            "source": "PUMP_FUN",
            "fee": 5000,
            "fee_payer": "Wallet66666666666666666666666666666666666666",
            "description": "Buy 5000 MEME with 1 SOL on Pump.fun",
            "accountData": [],
            "tokenTransfers": [
                {
                    "from_user_account": "Wallet66666666666666666666666666666666666666",
                    "to_user_account": "PumpBonding6666666666666666666666666666666",
                    "token_amount": 1.0,
                    "mint": "So11111111111111111111111111111111111111112",
                    "token_standard": "native",
                },
                {
                    "from_user_account": "PumpBonding6666666666666666666666666666666",
                    "to_user_account": "Wallet66666666666666666666666666666666666666",
                    "token_amount": 5000.0,
                    "mint": "MemeCoinMint666666666666666666666666666666666",
                    "token_standard": "spl",
                },
            ],
            "nativeTransfers": [],
            "events": {},
        },
        "expected": {
            "wallet": "Wallet66666666666666666666666666666666666666",
            "direction": "buy",
            "protocol": "pump.fun",
            "token_in": {
                "mint": "MemeCoinMint666666666666666666666666666666666",
                "amount": "5000.0",
                "decimals": 9,
            },
            "token_out": {
                "mint": "So11111111111111111111111111111111111111112",
                "amount": "1.0",
                "decimals": 9,
            },
            "fee_sol": "0.000005",
        },
    },
    # ── Fixture 2: Sell meme coin for SOL ───────────────────
    {
        "id": "pumpfun_sell_meme_002",
        "description": "Sell: 2000 MEME -> 0.3 SOL on Pump.fun",
        "input": {
            "signature": "5KtPnPumpSellMeme22222222222222222222222222222222",
            "slot": 225000202,
            "timestamp": 1714000360,
            "type": "SWAP",
            "source": "PUMP_FUN",
            "fee": 5000,
            "fee_payer": "Wallet77777777777777777777777777777777777777",
            "description": "Sell 2000 MEME for 0.3 SOL on Pump.fun",
            "accountData": [],
            "tokenTransfers": [
                {
                    "from_user_account": "Wallet77777777777777777777777777777777777777",
                    "to_user_account": "PumpBonding7777777777777777777777777777777",
                    "token_amount": 2000.0,
                    "mint": "MemeCoinMint777777777777777777777777777777777",
                    "token_standard": "spl",
                },
                {
                    "from_user_account": "PumpBonding7777777777777777777777777777777",
                    "to_user_account": "Wallet77777777777777777777777777777777777777",
                    "token_amount": 0.3,
                    "mint": "So11111111111111111111111111111111111111112",
                    "token_standard": "native",
                },
            ],
            "nativeTransfers": [],
            "events": {},
        },
        "expected": {
            "wallet": "Wallet77777777777777777777777777777777777777",
            "direction": "sell",
            "protocol": "pump.fun",
            "token_in": {
                "mint": "So11111111111111111111111111111111111111112",
                "amount": "0.3",
                "decimals": 9,
            },
            "token_out": {
                "mint": "MemeCoinMint777777777777777777777777777777777",
                "amount": "2000.0",
                "decimals": 9,
            },
            "fee_sol": "0.000005",
        },
    },
]
