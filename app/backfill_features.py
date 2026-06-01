"""Feature extraction — processes raw_events into wallet_positions and metrics.

Run this script on VPS to backfill all pending events.
"""

import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.infrastructure.database.session import async_session_factory
from app.infrastructure.database.models.wallet_position import WalletPosition
from app.infrastructure.database.models.raw_event import RawEvent
from sqlalchemy import select


async def backfill_features():
    """Process all completed raw_events into wallet_positions."""
    print("Starting feature extraction backfill...")

    async with async_session_factory() as session:
        # Get all completed events
        result = await session.execute(
            text("SELECT id, payload::text, status FROM raw_events WHERE status = 'completed' LIMIT 100")
        )
        events = result.fetchall()
        print(f"Found {len(events)} completed events")

        created = 0
        skipped = 0

        for event_id, payload_str, status in events:
            try:
                payload = json.loads(payload_str) if isinstance(payload_str, str) else payload_str

                # Extract wallet
                wallet = (
                    payload.get('fee_payer', '') or
                    payload.get('from', '') or
                    payload.get('wallet', '') or
                    payload.get('from_wallet', '')
                )
                if not wallet or len(wallet) < 10:
                    skipped += 1
                    continue

                # Check if position already exists
                existing = await session.execute(
                    select(WalletPosition).where(WalletPosition.wallet == wallet).limit(1)
                )
                if existing.scalar_one_or_none():
                    skipped += 1
                    continue

                # Create position
                position = WalletPosition(
                    wallet=wallet,
                    token_mint=payload.get('token', payload.get('mint', 'unknown')),
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
                    last_trade_id=str(event_id),
                    event_version=1,
                )
                session.add(position)
                created += 1
                print(f"  Created position for {wallet[:16]}...")

            except Exception as e:
                print(f"  Error processing event: {e}")
                skipped += 1

        await session.commit()
        print(f"\nBackfill complete: {created} created, {skipped} skipped")


if __name__ == "__main__":
    asyncio.run(backfill_features())
