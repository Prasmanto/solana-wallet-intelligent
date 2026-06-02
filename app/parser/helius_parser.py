"""Helius payload parser — extracts wallet, token, and trade data from Helius webhooks.

Based on forensic analysis of 92,301 real Helius events:
- fee_payer is ALWAYS empty
- token_transfers.from/to are ALWAYS empty
- Best sources: events.swap, description, account_data

Priority chain for wallet extraction:
1. events.swap.tokenOutputs[0].userAccount
2. events.swap.tokenInputs[0].userAccount
3. events.swap.nativeInput.account
4. events.swap.nativeOutput.account
5. Parse first wallet from description
6. account_data[0].account fallback
"""

from __future__ import annotations

import re
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

SOL_MINTS = {
    "So11111111111111111111111111111111111111112",
    "11111111111111111111111111111111",
}


def is_valid_solana_address(addr: str) -> bool:
    """Check if string looks like a valid Solana address (32-44 chars, base58)."""
    if not addr or not isinstance(addr, str):
        return False
    if len(addr) < 30 or len(addr) > 50:
        return False
    # Basic base58 check
    return bool(re.match(r'^[1-9A-HJ-NP-Za-km-z]+$', addr))


def extract_wallet(payload: dict[str, Any]) -> tuple[str, str, float]:
    """Extract wallet address from Helius payload using priority chain.
    
    Returns:
        (wallet_address, extraction_source, confidence)
    """
    # 1. events.swap.tokenOutputs[0].userAccount
    swap = payload.get("events", {}).get("swap", {})
    if swap:
        outputs = swap.get("tokenOutputs", [])
        if outputs and isinstance(outputs, list):
            user_account = outputs[0].get("userAccount", "")
            if is_valid_solana_address(user_account):
                return user_account, "events.swap.tokenOutputs", 0.95

        inputs = swap.get("tokenInputs", [])
        if inputs and isinstance(inputs, list):
            user_account = inputs[0].get("userAccount", "")
            if is_valid_solana_address(user_account):
                return user_account, "events.swap.tokenInputs", 0.90

        native_in = swap.get("nativeInput")
        if native_in and isinstance(native_in, dict):
            account = native_in.get("account", "")
            if is_valid_solana_address(account):
                return account, "events.swap.nativeInput", 0.85

        native_out = swap.get("nativeOutput")
        if native_out and isinstance(native_out, dict):
            account = native_out.get("account", "")
            if is_valid_solana_address(account):
                return account, "events.swap.nativeOutput", 0.85

    # 2. Parse first wallet from description
    desc = payload.get("description", "")
    if desc:
        parts = desc.split(" ")
        if parts and is_valid_solana_address(parts[0]):
            return parts[0], "description", 0.75

    # 3. token_transfers[0].fromUserAccount or .toUserAccount
    tt = payload.get("token_transfers", [])
    if tt and isinstance(tt, list) and len(tt) > 0:
        from_user = tt[0].get("fromUserAccount", "")
        if is_valid_solana_address(from_user):
            return from_user, "token_transfers.from", 0.70
        to_user = tt[0].get("toUserAccount", "")
        if is_valid_solana_address(to_user):
            return to_user, "token_transfers.to", 0.70

    # 4. native_transfers[0].fromUserAccount or .toUserAccount
    nt = payload.get("native_transfers", [])
    if nt and isinstance(nt, list) and len(nt) > 0:
        from_user = nt[0].get("fromUserAccount", "")
        if is_valid_solana_address(from_user):
            return from_user, "native_transfers.from", 0.65
        to_user = nt[0].get("toUserAccount", "")
        if is_valid_solana_address(to_user):
            return to_user, "native_transfers.to", 0.65

    # 5. account_data[0].account fallback
    ad = payload.get("account_data", [])
    if ad and isinstance(ad, list) and len(ad) > 0:
        account = ad[0].get("account", "")
        if is_valid_solana_address(account):
            return account, "account_data[0]", 0.45

    return "", "none", 0.0


def extract_tokens(payload: dict[str, Any]) -> tuple[str, str, str, str, float, float]:
    """Extract token information from Helius payload.
    
    Returns:
        (input_token, output_token, primary_token, direction, amount_in, amount_out)
    """
    input_token = ""
    output_token = ""
    amount_in = 0.0
    amount_out = 0.0

    # Try events.swap first
    swap = payload.get("events", {}).get("swap", {})
    if swap:
        # Token inputs (what was sold)
        token_inputs = swap.get("tokenInputs", [])
        if token_inputs and isinstance(token_inputs, list) and len(token_inputs) > 0:
            input_token = token_inputs[0].get("mint", "")
            raw_amount = token_inputs[0].get("rawTokenAmount", {})
            if raw_amount:
                decimals = raw_amount.get("decimals", 0)
                token_amount = int(raw_amount.get("tokenAmount", 0))
                amount_in = token_amount / (10 ** decimals) if decimals > 0 else float(token_amount)

        # Token outputs (what was bought)
        token_outputs = swap.get("tokenOutputs", [])
        if token_outputs and isinstance(token_outputs, list) and len(token_outputs) > 0:
            output_token = token_outputs[0].get("mint", "")
            raw_amount = token_outputs[0].get("rawTokenAmount", {})
            if raw_amount:
                decimals = raw_amount.get("decimals", 0)
                token_amount = int(raw_amount.get("tokenAmount", 0))
                amount_out = token_amount / (10 ** decimals) if decimals > 0 else float(token_amount)

        # Native input (SOL sold)
        native_input = swap.get("nativeInput")
        if native_input and isinstance(native_input, dict):
            input_token = "So11111111111111111111111111111111111111112"
            raw = native_input.get("amount", 0)
            amount_in = float(int(raw)) / 1e9 if raw else 0.0  # lamports to SOL

        # Native output (SOL bought)
        native_output = swap.get("nativeOutput")
        if native_output and isinstance(native_output, dict):
            output_token = "So11111111111111111111111111111111111111112"
            raw = native_output.get("amount", 0)
            amount_out = float(int(raw)) / 1e9 if raw else 0.0  # lamports to SOL

    # Fallback to token_transfers
    if not input_token and not output_token:
        tt = payload.get("token_transfers", [])
        if tt and isinstance(tt, list) and len(tt) > 0:
            # Use the mint from the first transfer
            output_token = tt[0].get("mint", "")
            raw_amount = tt[0].get("tokenAmount", tt[0].get("amount", 0))
            try:
                amount_out = float(raw_amount) if raw_amount else 0.0
            except (ValueError, TypeError):
                amount_out = 0.0

    # Fallback to native_transfers
    if not input_token and not output_token:
        nt = payload.get("native_transfers", [])
        if nt and isinstance(nt, list) and len(nt) > 0:
            output_token = "So11111111111111111111111111111111111111112"
            raw = nt[0].get("amount", 0)
            try:
                amount_out = float(int(raw)) / 1e9 if raw else 0.0
            except (ValueError, TypeError):
                amount_out = 0.0

    # Determine primary token and direction
    primary_token = output_token or input_token or ""
    
    # Determine direction based on SOL flow
    if input_token in SOL_MINTS and output_token not in SOL_MINTS:
        direction = "BUY"  # Paid SOL, received token
        primary_token = output_token
    elif output_token in SOL_MINTS and input_token not in SOL_MINTS:
        direction = "SELL"  # Paid token, received SOL
        primary_token = input_token
    elif input_token and output_token:
        direction = "SWAP"  # Token-to-token swap
    elif output_token:
        direction = "BUY"
        primary_token = output_token
    elif input_token:
        direction = "SELL"
        primary_token = input_token
    else:
        direction = "UNKNOWN"

    return input_token, output_token, primary_token, direction, amount_in, amount_out


def parse_helius_event(event_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a Helius event into a normalized trade record.
    
    Returns normalized dict or None if unparseable.
    """
    signature = payload.get("signature", "")
    if not signature:
        return None

    # Extract wallet
    wallet, wallet_source, wallet_confidence = extract_wallet(payload)
    
    # Extract tokens
    input_token, output_token, primary_token, direction, amount_in, amount_out = extract_tokens(payload)
    
    # Determine amount for position tracking
    amount = amount_out if direction == "BUY" else amount_in if direction == "SELL" else max(amount_in, amount_out)
    
    # Determine event type for position tracking
    event_type = direction if direction in ("BUY", "SELL") else "TRANSFER"
    
    # Get source info
    source = payload.get("source", payload.get("tx_type", "UNKNOWN"))
    tx_type = payload.get("tx_type", "UNKNOWN")
    slot = payload.get("slot", 0)
    block_time = payload.get("block_time", 0)
    fee = payload.get("fee", 0)
    
    return {
        "event_id": event_id,
        "signature": signature,
        "wallet": wallet,
        "wallet_source": wallet_source,
        "wallet_confidence": wallet_confidence,
        "source": source,
        "tx_type": tx_type,
        "slot": slot,
        "timestamp": block_time,
        "input_token": input_token,
        "output_token": output_token,
        "primary_token": primary_token,
        "token": primary_token,  # alias for compatibility
        "direction": direction,
        "event_type": event_type,
        "amount_in": amount_in,
        "amount_out": amount_out,
        "amount": amount,
        "fee": fee,
        "confidence": wallet_confidence,
        "is_valid": wallet != "",
        "token_source": "events.swap" if payload.get("events", {}).get("swap") else "token_transfers",
    }
