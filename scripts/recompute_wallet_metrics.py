#!/usr/bin/env python3
"""Recompute wallet_metrics and wallet_features from wallet_positions.

This script:
1. Reads all wallet_positions
2. Computes wallet_metrics per wallet
3. Computes wallet_features per wallet
4. Upserts idempotently
5. Logs statistics

Usage:
    docker exec solana_intel_api python3 /code/scripts/recompute_wallet_metrics.py
"""

import asyncio
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
from app.infrastructure.database.models.wallet_position import WalletPosition
from app.infrastructure.database.models.wallet_metrics import WalletMetrics
from app.infrastructure.database.models.wallet_feature import WalletFeature


async def recompute():
    """Main recomputation function."""
    print("=" * 60)
    print("RECOMPUTING WALLET METRICS & FEATURES")
    print("=" * 60)
    print()

    # Initialize database
    db_manager = DatabaseManager(settings)
    await db_manager.connect()
    print("Database connected")

    session = db_manager.get_session()
    
    try:
        # Get total positions
        total = (await session.execute(select(func.count(WalletPosition.id)))).scalar() or 0
        print(f"Total wallet_positions: {total:,}")
        
        # Get unique wallets
        wallet_result = await session.execute(
            select(WalletPosition.wallet).distinct()
        )
        wallets = [row[0] for row in wallet_result]
        print(f"Unique wallets: {len(wallets):,}")
        print()

        # Compute wallet_metrics
        print("Computing wallet_metrics...")
        metrics_stats = {"created": 0, "updated": 0, "errors": 0}
        
        start_time = time.time()
        for i, wallet in enumerate(wallets):
            try:
                result = await compute_wallet_metrics(session, wallet)
                if result == "created":
                    metrics_stats["created"] += 1
                elif result == "updated":
                    metrics_stats["updated"] += 1
            except Exception as e:
                metrics_stats["errors"] += 1
                print(f"  Error for wallet {wallet[:16]}: {e}")
            
            if (i + 1) % 1000 == 0:
                elapsed = time.time() - start_time
                rate = (i + 1) / elapsed
                print(f"  Progress: {i + 1:,}/{len(wallets):,} ({(i + 1) / len(wallets) * 100:.1f}%) | Rate: {rate:.0f}/sec")
        
        await session.commit()
        print(f"\nwallet_metrics: {metrics_stats['created']} created, {metrics_stats['updated']} updated, {metrics_stats['errors']} errors")
        
        # Compute wallet_features
        print("\nComputing wallet_features...")
        features_stats = {"created": 0, "updated": 0, "errors": 0}
        
        start_time = time.time()
        for i, wallet in enumerate(wallets):
            try:
                result = await compute_wallet_features(session, wallet)
                if result == "created":
                    features_stats["created"] += 1
                elif result == "updated":
                    features_stats["updated"] += 1
            except Exception as e:
                features_stats["errors"] += 1
                print(f"  Error for wallet {wallet[:16]}: {e}")
            
            if (i + 1) % 1000 == 0:
                elapsed = time.time() - start_time
                rate = (i + 1) / elapsed
                print(f"  Progress: {i + 1:,}/{len(wallets):,} ({(i + 1) / len(wallets) * 100:.1f}%) | Rate: {rate:.0f}/sec")
        
        await session.commit()
        print(f"\nwallet_features: {features_stats['created']} created, {features_stats['updated']} updated, {features_stats['errors']} errors")
        
        # Final counts
        print("\n" + "=" * 60)
        print("RECOMPUTATION COMPLETE")
        print("=" * 60)
        
        metrics_count = (await session.execute(select(func.count(WalletMetrics.id)))).scalar() or 0
        features_count = (await session.execute(select(func.count(WalletFeature.id)))).scalar() or 0
        
        print(f"\nwallet_positions:  {total:,}")
        print(f"wallet_metrics:    {metrics_count:,}")
        print(f"wallet_features:   {features_count:,}")
        
        print("\n" + "=" * 60)
        
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        await session.rollback()
    finally:
        await session.close()
        await db_manager.close()


async def compute_wallet_metrics(session, wallet: str) -> str:
    """Compute metrics for a single wallet."""
    # Get all positions
    result = await session.execute(
        select(WalletPosition).where(WalletPosition.wallet == wallet)
    )
    positions = result.scalars().all()
    
    if not positions:
        return "skipped"
    
    # Compute aggregated metrics
    total_buys = sum(p.total_buys for p in positions)
    total_sells = sum(p.total_sells for p in positions)
    total_trades = total_buys + total_sells
    
    total_buy_volume = sum(float(p.total_buy_volume) for p in positions)
    total_sell_volume = sum(float(p.total_sell_volume) for p in positions)
    total_volume = total_buy_volume + total_sell_volume
    
    unique_tokens = len(set(p.token_mint for p in positions))
    active_positions = sum(1 for p in positions if float(p.position_size) > 0)
    
    position_sizes = [float(p.position_size) for p in positions]
    avg_position_size = sum(position_sizes) / len(position_sizes) if position_sizes else 0
    max_position_size = max(position_sizes) if position_sizes else 0
    
    hold_durations = [p.hold_duration_seconds for p in positions]
    avg_hold_duration = sum(hold_durations) / len(hold_durations) if hold_durations else 0
    
    total_fees = sum(float(p.total_fees_paid) for p in positions)
    total_pnl = sum(float(p.realized_pnl) for p in positions)
    total_cost = sum(float(p.total_cost_basis) for p in positions)
    total_roi = (total_pnl / total_cost * 100) if total_cost > 0 else 0
    
    # Timestamps
    first_trade = None
    for p in positions:
        if p.first_buy_at:
            if first_trade is None or p.first_buy_at < first_trade:
                first_trade = p.first_buy_at
    
    last_trade = None
    for p in positions:
        if p.last_trade_at:
            if last_trade is None or p.last_trade_at > last_trade:
                last_trade = p.last_trade_at
    
    now = datetime.now(timezone.utc)
    
    # Check if exists
    existing = await session.execute(
        select(WalletMetrics).where(WalletMetrics.wallet == wallet)
    )
    existing_metrics = existing.scalar_one_or_none()
    
    metrics_data = {
        "wallet": wallet,
        "total_realized_pnl": total_pnl,
        "total_realized_roi": total_roi,
        "total_fees_paid": total_fees,
        "net_pnl": total_pnl,
        "total_wins": 0,
        "total_losses": 0,
        "win_rate": 0.0,
        "avg_win_pnl": 0.0,
        "avg_loss_pnl": 0.0,
        "best_trade_pnl": 0.0,
        "worst_trade_pnl": 0.0,
        "best_trade_token": "",
        "worst_trade_token": "",
        "total_unique_tokens": unique_tokens,
        "active_positions": active_positions,
        "total_trades": total_trades,
        "total_buys": total_buys,
        "total_sells": total_sells,
        "total_buy_volume": total_buy_volume,
        "total_sell_volume": total_sell_volume,
        "total_volume": total_volume,
        "avg_hold_duration_seconds": int(avg_hold_duration),
        "avg_position_size": avg_position_size,
        "max_position_size": max_position_size,
        "first_trade_at": first_trade,
        "last_trade_at": last_trade,
        "last_updated_at": now,
        "metadata_": {"source": "backfill", "reason": "price_unavailable"},
    }
    
    if existing_metrics is None:
        # Create new
        wallet_metrics = WalletMetrics(**metrics_data)
        session.add(wallet_metrics)
        return "created"
    else:
        # Update existing
        for key, value in metrics_data.items():
            if key != "wallet":
                setattr(existing_metrics, key, value)
        existing_metrics.metrics_version += 1
        return "updated"


async def compute_wallet_features(session, wallet: str) -> str:
    """Compute features for a single wallet."""
    # Get all positions
    result = await session.execute(
        select(WalletPosition).where(WalletPosition.wallet == wallet)
    )
    positions = result.scalars().all()
    
    if not positions:
        return "skipped"
    
    # Compute features
    total_buys = sum(p.total_buys for p in positions)
    total_sells = sum(p.total_sells for p in positions)
    total_volume = sum(float(p.total_buy_volume) + float(p.total_sell_volume) for p in positions)
    unique_tokens = len(set(p.token_mint for p in positions))
    
    # Activity frequency (trades per day)
    if positions:
        first_trade = min(
            (p.first_buy_at or p.last_trade_at for p in positions if p.first_buy_at or p.last_trade_at),
            default=None
        )
        last_trade = max(
            (p.last_trade_at for p in positions if p.last_trade_at),
            default=None
        )
        
        if first_trade and last_trade:
            days_active = max(1, (last_trade - first_trade).days)
            tx_frequency = total_buys + total_sells
            avg_interval = days_active / max(1, tx_frequency)
        else:
            tx_frequency = total_buys + total_sells
            avg_interval = 0
    else:
        tx_frequency = 0
        avg_interval = 0
    
    # Buy/sell ratio
    buy_sell_ratio = total_buys / total_sells if total_sells > 0 else total_buys
    
    # Interaction score (simple: total trades * unique tokens)
    interaction_score = (total_buys + total_sells) * unique_tokens
    
    # Check if exists for "all" time window
    existing = await session.execute(
        select(WalletFeature).where(
            WalletFeature.wallet_address == wallet,
            WalletFeature.time_window == "all",
        )
    )
    existing_feature = existing.scalar_one_or_none()
    
    now = datetime.now(timezone.utc)
    
    feature_data = {
        "wallet_address": wallet,
        "time_window": "all",
        "volume": total_volume,
        "tx_frequency": tx_frequency,
        "avg_interval": avg_interval,
        "token_diversity": unique_tokens,
        "buy_count": total_buys,
        "sell_count": total_sells,
        "transfer_count": 0,
        "buy_sell_ratio": buy_sell_ratio,
        "interaction_score": interaction_score,
        "features_json": {
            "total_volume": total_volume,
            "unique_tokens": unique_tokens,
            "total_trades": total_buys + total_sells,
        },
        "computed_at": now,
    }
    
    if existing_feature is None:
        # Create new
        wallet_feature = WalletFeature(**feature_data)
        session.add(wallet_feature)
        return "created"
    else:
        # Update existing
        for key, value in feature_data.items():
            if key not in ("wallet_address", "time_window"):
                setattr(existing_feature, key, value)
        return "updated"


if __name__ == "__main__":
    asyncio.run(recompute())
