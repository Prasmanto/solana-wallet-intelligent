#!/usr/bin/env python3
"""Reprocess all Helius events with fixed parser.

This script:
1. Reads all raw_events from database
2. Parses with new Helius parser
3. Upserts wallet_positions idempotently
4. Tracks statistics

Usage:
    python scripts/reprocess_helius_events.py
"""

import asyncio
import json
import sys
import os
import time
from datetime import datetime, timezone
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config.settings import settings
from app.infrastructure.database.manager import DatabaseManager
from app.infrastructure.database.models.raw_event import RawEvent
from app.infrastructure.database.models.wallet_position import WalletPosition
from app.parser.helius_parser import parse_helius_event, is_valid_solana_address


# Statistics tracking
stats = {
    "total_events": 0,
    "parsed_successfully": 0,
    "wallet_extracted": 0,
    "positions_created": 0,
    "positions_updated": 0,
    "positions_skipped": 0,
    "parse_errors": 0,
    "wallet_sources": defaultdict(int),
    "token_sources": defaultdict(int),
    "confidence_buckets": defaultdict(int),
    "direction_counts": defaultdict(int),
    "errors": [],
}


async def reprocess_events():
    """Main reprocessing function."""
    print("=" * 70)
    print("REPROCESSING 92K HELIUS EVENTS WITH FIXED PARSER")
    print("=" * 70)
    print()

    # Initialize database
    db_manager = DatabaseManager(settings)
    await db_manager.connect()
    print("Database connected")

    session = db_manager.get_session()
    
    try:
        # Get total count
        total = (await session.execute(select(func.count(RawEvent.id)))).scalar() or 0
        stats["total_events"] = total
        print(f"Total events to process: {total:,}")
        print()

        # Process in batches
        batch_size = 1000
        offset = 0
        processed = 0
        start_time = time.time()

        while offset < total:
            # Fetch batch
            result = await session.execute(
                select(RawEvent)
                .order_by(RawEvent.created_at.asc())
                .offset(offset)
                .limit(batch_size)
            )
            events = result.scalars().all()
            
            if not events:
                break

            # Process each event
            for event in events:
                try:
                    await process_event(session, event)
                    processed += 1
                except Exception as e:
                    stats["parse_errors"] += 1
                    stats["errors"].append({
                        "event_id": event.event_id[:16],
                        "error": str(e)[:100]
                    })
                    if len(stats["errors"]) > 100:
                        stats["errors"] = stats["errors"][-100:]

            # Commit batch
            await session.commit()

            # Progress report
            elapsed = time.time() - start_time
            rate = processed / elapsed if elapsed > 0 else 0
            eta = (total - offset) / rate if rate > 0 else 0
            
            print(f"\rProgress: {processed:,}/{total:,} ({processed/total*100:.1f}%) "
                  f"| Rate: {rate:.0f}/sec | ETA: {eta:.0f}s", end="", flush=True)

            offset += batch_size

        print("\n")
        
        # Final commit
        await session.commit()

        # Print results
        print_results()

    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        await session.rollback()
    finally:
        await session.close()
        await db_manager.close()


async def process_event(session, event: RawEvent):
    """Process a single raw event."""
    payload = event.payload
    if not payload:
        return

    # Parse with Helius parser
    parsed = parse_helius_event(event.event_id, payload)
    
    if not parsed:
        stats["parse_errors"] += 1
        return

    stats["parsed_successfully"] += 1

    # Track wallet source
    wallet_source = parsed.get("wallet_source", "none")
    stats["wallet_sources"][wallet_source] += 1

    # Track token source
    token_source = parsed.get("token_source", "none")
    stats["token_sources"][token_source] += 1

    # Track confidence
    confidence = parsed.get("confidence", 0)
    if confidence >= 0.9:
        stats["confidence_buckets"]["high_90+"] += 1
    elif confidence >= 0.7:
        stats["confidence_buckets"]["medium_70-90"] += 1
    elif confidence >= 0.5:
        stats["confidence_buckets"]["low_50-70"] += 1
    else:
        stats["confidence_buckets"]["very_low_<50"] += 1

    # Track direction
    direction = parsed.get("direction", "UNKNOWN")
    stats["direction_counts"][direction] += 1

    # Extract wallet
    wallet = parsed.get("wallet", "")
    if not wallet or not is_valid_solana_address(wallet):
        return

    stats["wallet_extracted"] += 1

    # Get token
    token_mint = parsed.get("primary_token", "") or parsed.get("token", "")
    if not token_mint:
        return

    # Get amount
    amount = parsed.get("amount", 0)
    if amount <= 0:
        # Try to get from amount_in or amount_out
        amount = parsed.get("amount_out", 0) or parsed.get("amount_in", 0)

    # Get event type
    event_type = parsed.get("direction", "TRANSFER")
    if event_type not in ("BUY", "SELL", "TRANSFER"):
        event_type = "TRANSFER"

    # Get signature for idempotency (truncate to fit VARCHAR(36))
    signature = parsed.get("signature", event.event_id)
    if len(signature) > 36:
        signature = signature[:36]

    # Upsert wallet position
    await upsert_position(
        session=session,
        wallet=wallet,
        token_mint=token_mint,
        event_type=event_type,
        amount=amount,
        signature=signature,
        fee=parsed.get("fee", 0),
        event_id=event.event_id,
    )


async def upsert_position(
    session,
    wallet: str,
    token_mint: str,
    event_type: str,
    amount: float,
    signature: str,
    fee: int,
    event_id: str,
):
    """Upsert wallet position idempotently."""
    # Check if position exists
    result = await session.execute(
        select(WalletPosition).where(
            WalletPosition.wallet == wallet,
            WalletPosition.token_mint == token_mint,
        )
    )
    position = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if position is None:
        # Create new position
        position = WalletPosition(
            wallet=wallet,
            token_mint=token_mint,
            position_size=0,
            avg_cost_basis=0,
            total_cost_basis=0,
            realized_pnl=0,
            realized_roi=0,
            total_buys=0,
            total_sells=0,
            total_buy_volume=0,
            total_sell_volume=0,
            total_fees_paid=0,
            hold_duration_seconds=0,
            last_trade_id=signature,
            event_version=1,
            first_buy_at=now if event_type == "BUY" else None,
            first_sell_at=now if event_type == "SELL" else None,
            last_buy_at=now if event_type == "BUY" else None,
            last_sell_at=now if event_type == "SELL" else None,
            last_trade_at=now,
            last_processed_at=now,
            metadata_={
                "source": "helius_backfill",
                "event_id": event_id,
            },
        )
        session.add(position)
        stats["positions_created"] += 1
    else:
        # Check if already processed this signature
        if position.last_trade_id == signature:
            stats["positions_skipped"] += 1
            return

        # Update existing position
        if event_type == "BUY" and amount > 0:
            if position.position_size == 0:
                position.avg_cost_basis = amount / amount if amount else 0
            else:
                position.avg_cost_basis = (
                    (position.position_size * float(position.avg_cost_basis)) + amount
                ) / (position.position_size + amount) if (position.position_size + amount) else 0

            position.position_size += amount
            position.total_buys += 1
            position.total_buy_volume += amount
            position.first_buy_at = position.first_buy_at or now
            position.last_buy_at = now

        elif event_type == "SELL" and amount > 0:
            if position.position_size > 0:
                sell_proceeds = amount * float(position.avg_cost_basis)
                position.realized_pnl += sell_proceeds - (amount * float(position.avg_cost_basis))
                position.position_size = max(0, position.position_size - amount)
                position.total_sells += 1
                position.total_sell_volume += amount
                position.first_sell_at = position.first_sell_at or now
                position.last_sell_at = now

                if position.total_cost_basis > 0:
                    position.realized_roi = float(
                        (position.realized_pnl / position.total_cost_basis) * 100
                    )

        # Update common fields
        position.last_trade_id = signature
        position.last_trade_at = now
        position.last_processed_at = now
        position.event_version += 1
        position.total_fees_paid += fee / 1e9  # lamports to SOL

        stats["positions_updated"] += 1


def print_results():
    """Print final results."""
    print("=" * 70)
    print("REPROCESSING COMPLETE")
    print("=" * 70)
    
    print(f"\n📊 SUMMARY")
    print(f"-" * 40)
    print(f"Total events:        {stats['total_events']:>10,}")
    print(f"Successfully parsed: {stats['parsed_successfully']:>10,}")
    print(f"Wallet extracted:    {stats['wallet_extracted']:>10,}")
    print(f"Positions created:   {stats['positions_created']:>10,}")
    print(f"Positions updated:   {stats['positions_updated']:>10,}")
    print(f"Positions skipped:   {stats['positions_skipped']:>10,}")
    print(f"Parse errors:        {stats['parse_errors']:>10,}")
    
    recovery_rate = stats['wallet_extracted'] / stats['total_events'] * 100 if stats['total_events'] > 0 else 0
    print(f"\nRecovery rate:       {recovery_rate:>9.1f}%")
    
    print(f"\n📍 WALLET SOURCE DISTRIBUTION")
    print(f"-" * 40)
    for source, count in sorted(stats['wallet_sources'].items(), key=lambda x: -x[1]):
        pct = count / stats['parsed_successfully'] * 100 if stats['parsed_successfully'] > 0 else 0
        print(f"  {source:<35} {count:>8,} ({pct:>5.1f}%)")
    
    print(f"\n🪙 TOKEN SOURCE DISTRIBUTION")
    print(f"-" * 40)
    for source, count in sorted(stats['token_sources'].items(), key=lambda x: -x[1]):
        pct = count / stats['parsed_successfully'] * 100 if stats['parsed_successfully'] > 0 else 0
        print(f"  {source:<35} {count:>8,} ({pct:>5.1f}%)")
    
    print(f"\n📈 CONFIDENCE DISTRIBUTION")
    print(f"-" * 40)
    for bucket, count in sorted(stats['confidence_buckets'].items()):
        pct = count / stats['parsed_successfully'] * 100 if stats['parsed_successfully'] > 0 else 0
        print(f"  {bucket:<35} {count:>8,} ({pct:>5.1f}%)")
    
    print(f"\n🔄 DIRECTION DISTRIBUTION")
    print(f"-" * 40)
    for direction, count in sorted(stats['direction_counts'].items(), key=lambda x: -x[1]):
        pct = count / stats['parsed_successfully'] * 100 if stats['parsed_successfully'] > 0 else 0
        print(f"  {direction:<35} {count:>8,} ({pct:>5.1f}%)")
    
    if stats['errors']:
        print(f"\n⚠️  RECENT ERRORS (last 10)")
        print(f"-" * 40)
        for err in stats['errors'][-10:]:
            print(f"  {err['event_id']:<20} {err['error'][:50]}")


if __name__ == "__main__":
    asyncio.run(reprocess_events())
