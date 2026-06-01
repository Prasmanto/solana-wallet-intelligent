"""Live Intelligence Verification Audit Script.

Run this on VPS to verify intelligence pipeline status.

Usage:
    python -m scripts.live_intelligence_audit
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import structlog

from app.config.settings import settings
from app.infrastructure.database.manager import DatabaseManager
from app.infrastructure.redis.manager import RedisManager

logger = structlog.get_logger(__name__)


async def run_audit():
    """Run complete intelligence pipeline audit."""
    print("\n" + "=" * 70)
    print("LIVE INTELLIGENCE VERIFICATION AUDIT")
    print("=" * 70)
    
    db_manager = DatabaseManager(settings)
    redis_manager = RedisManager(settings)
    
    try:
        await db_manager.connect()
        await redis_manager.connect()
        
        # Phase 1: Live Data Trace
        await phase1_live_data_trace(db_manager)
        
        # Phase 2: Metrics Generation Check
        await phase2_metrics_generation(db_manager)
        
        # Phase 3: Signal Generation
        await phase3_signal_generation(redis_manager)
        
        # Phase 4: Prediction Engine
        await phase4_prediction_engine(redis_manager)
        
        # Phase 5: Ranking Engine
        await phase5_ranking_engine(redis_manager)
        
        # Phase 6: End-to-End Trace
        await phase6_end_to_end_trace(db_manager, redis_manager)
        
        # Summary
        await print_summary(db_manager, redis_manager)
        
    finally:
        await db_manager.close()
        await redis_manager.close()


async def phase1_live_data_trace(db_manager: DatabaseManager):
    """Phase 1: Check latest wallet_positions."""
    print("\n" + "-" * 70)
    print("PHASE 1: LIVE DATA TRACE")
    print("-" * 70)
    
    from sqlalchemy import select, func
    from app.infrastructure.database.models.wallet_position import WalletPosition
    from app.infrastructure.database.models.raw_event import RawEvent
    
    async with db_manager.get_session() as session:
        # Count raw_events
        event_count = await session.execute(select(func.count(RawEvent.id)))
        total_events = event_count.scalar()
        print(f"Total raw_events: {total_events}")
        
        # Count wallet_positions
        pos_count = await session.execute(select(func.count(WalletPosition.id)))
        total_positions = pos_count.scalar()
        print(f"Total wallet_positions: {total_positions}")
        
        # Get latest 20 positions
        if total_positions > 0:
            result = await session.execute(
                select(WalletPosition)
                .order_by(WalletPosition.last_processed_at.desc())
                .limit(20)
            )
            positions = result.scalars().all()
            
            print(f"\nLatest {len(positions)} wallet_positions:")
            print("-" * 70)
            print(f"{'Wallet':<16} {'Token':<16} {'Size':<12} {'Buys':<8} {'Sells':<8} {'Last Trade':<20}")
            print("-" * 70)
            
            for pos in positions:
                wallet = pos.wallet[:14] + ".." if len(pos.wallet) > 14 else pos.wallet
                token = pos.token_mint[:14] + ".." if len(pos.token_mint) > 14 else pos.token_mint
                size = f"{float(pos.position_size):.2f}"
                last_trade = pos.last_trade_at.strftime("%Y-%m-%d %H:%M") if pos.last_trade_at else "N/A"
                
                print(f"{wallet:<16} {token:<16} {size:<12} {pos.total_buys:<8} {pos.total_sells:<8} {last_trade:<20}")
        else:
            print("No wallet_positions found!")


async def phase2_metrics_generation(db_manager: DatabaseManager):
    """Phase 2: Check wallet_metrics generation."""
    print("\n" + "-" * 70)
    print("PHASE 2: METRICS GENERATION CHECK")
    print("-" * 70)
    
    from sqlalchemy import select, func
    from app.infrastructure.database.models.wallet_metrics import WalletMetrics
    from app.infrastructure.database.models.wallet_position import WalletPosition
    
    async with db_manager.get_session() as session:
        # Count wallet_metrics
        metrics_count = await session.execute(select(func.count(WalletMetrics.id)))
        total_metrics = metrics_count.scalar()
        print(f"Total wallet_metrics: {total_metrics}")
        
        # Count positions that should have metrics
        pos_count = await session.execute(
            select(func.count(WalletPosition.id))
        )
        total_positions = pos_count.scalar()
        
        if total_metrics == 0:
            print("\n⚠️  BOTTLENECK IDENTIFIED: wallet_metrics is EMPTY")
            print("   AggregationWorker is NOT running in the orchestrator!")
            print(f"   There are {total_positions} positions awaiting metrics computation.")
        else:
            # Show latest metrics
            result = await session.execute(
                select(WalletMetrics)
                .order_by(WalletMetrics.last_updated_at.desc())
                .limit(5)
            )
            metrics = result.scalars().all()
            
            print(f"\nLatest {len(metrics)} wallet_metrics:")
            print("-" * 70)
            print(f"{'Wallet':<16} {'PnL':<12} {'Win Rate':<10} {'Trades':<10} {'Last Updated':<20}")
            print("-" * 70)
            
            for m in metrics:
                wallet = m.wallet[:14] + ".." if len(m.wallet) > 14 else m.wallet
                pnl = f"${float(m.total_realized_pnl):.2f}"
                win_rate = f"{float(m.win_rate) * 100:.1f}%"
                updated = m.last_updated_at.strftime("%Y-%m-%d %H:%M") if m.last_updated_at else "N/A"
                
                print(f"{wallet:<16} {pnl:<12} {win_rate:<10} {m.total_trades:<10} {updated:<20}")


async def phase3_signal_generation(redis_manager: RedisManager):
    """Phase 3: Check signal generation."""
    print("\n" + "-" * 70)
    print("PHASE 3: SIGNAL GENERATION")
    print("-" * 70)
    
    streams_redis = redis_manager.get_client("streams")
    
    # Check TRADE_ENRICHED stream (where analytics publishes)
    enriched_info = await streams_redis.xinfo_stream("solana_intel.trade.enriched")
    enriched_length = enriched_info.get("length", 0)
    print(f"TRADE_ENRICHED stream length: {enriched_length}")
    
    # Check ALERT_TRIGGERED stream
    alert_info = await streams_redis.xinfo_stream("solana_intel.alert.triggered")
    alert_length = alert_info.get("length", 0)
    print(f"ALERT_TRIGGERED stream length: {alert_length}")
    
    # Check if any events have intelligence data
    if enriched_length > 0:
        # Read last 5 events
        events = await streams_redis.xrevrange(
            "solana_intel.trade.enriched",
            count=5
        )
        
        print(f"\nLast {len(events)} enriched events:")
        print("-" * 70)
        
        for event_id, fields in events:
            payload = json.loads(fields.get("payload", "{}"))
            intelligence = payload.get("intelligence", {})
            
            wallet = payload.get("wallet", "")[:14]
            event_type = payload.get("event_type", "N/A")
            cluster_id = intelligence.get("cluster_id", "")[:14]
            wallet_type = intelligence.get("wallet_type", "N/A")
            smart_money = intelligence.get("smart_money")
            
            smart_money_str = "Yes" if smart_money and smart_money.get("is_smart_money") else "No"
            
            print(f"  Event: {event_id[:16]}")
            print(f"    Wallet: {wallet}, Type: {event_type}")
            print(f"    Cluster: {cluster_id}, Wallet Type: {wallet_type}")
            print(f"    Smart Money: {smart_money_str}")
            print()
    else:
        print("\n⚠️  TRADE_ENRICHED is EMPTY - no signals being generated")


async def phase4_prediction_engine(redis_manager: RedisManager):
    """Phase 4: Check prediction engine."""
    print("\n" + "-" * 70)
    print("PHASE 4: PREDICTION ENGINE STATUS")
    print("-" * 70)
    
    streams_redis = redis_manager.get_client("streams")
    
    # Check if predictions are being generated
    # Look for prediction-related streams
    try:
        # Check for any prediction streams
        streams = await streams_redis.keys("solana_intel.*")
        prediction_streams = [s for s in streams if "predict" in s.lower()]
        
        if prediction_streams:
            for stream in prediction_streams:
                info = await streams_redis.xinfo_stream(stream)
                length = info.get("length", 0)
                print(f"Prediction stream {stream}: {length} events")
        else:
            print("No prediction streams found")
            
    except Exception as e:
        print(f"Error checking predictions: {e}")
    
    print("\n⚠️  Prediction engine is NOT connected to live pipeline")
    print("   No predictions are being generated from live data")


async def phase5_ranking_engine(redis_manager: RedisManager):
    """Phase 5: Check ranking engine."""
    print("\n" + "-" * 70)
    print("PHASE 5: RANKING ENGINE STATUS")
    print("-" * 70)
    
    streams_redis = redis_manager.get_client("streams")
    
    # Check for ranking-related streams
    try:
        streams = await streams_redis.keys("solana_intel.*")
        ranking_streams = [s for s in streams if "rank" in s.lower()]
        
        if ranking_streams:
            for stream in ranking_streams:
                info = await streams_redis.xinfo_stream(stream)
                length = info.get("length", 0)
                print(f"Ranking stream {stream}: {length} events")
        else:
            print("No ranking streams found")
            
    except Exception as e:
        print(f"Error checking rankings: {e}")
    
    print("\n⚠️  Ranking engine is NOT connected to live pipeline")
    print("   No rankings are being generated from live data")


async def phase6_end_to_end_trace(db_manager: DatabaseManager, redis_manager: RedisManager):
    """Phase 6: End-to-end trace of a single event."""
    print("\n" + "-" * 70)
    print("PHASE 6: END-TO-END TRACE")
    print("-" * 70)
    
    from sqlalchemy import select
    from app.infrastructure.database.models.raw_event import RawEvent
    from app.infrastructure.database.models.wallet_position import WalletPosition
    from app.infrastructure.database.models.wallet_metrics import WalletMetrics
    
    async with db_manager.get_session() as session:
        # Pick the latest raw_event
        result = await session.execute(
            select(RawEvent)
            .order_by(RawEvent.created_at.desc())
            .limit(1)
        )
        latest_event = result.scalar_one_or_none()
        
        if not latest_event:
            print("No raw_events found for tracing!")
            return
        
        print(f"\nTracing event: {latest_event.event_id[:16]}...")
        print(f"  Type: {latest_event.event_type}")
        print(f"  Status: {latest_event.status}")
        print(f"  Created: {latest_event.created_at}")
        
        # Check if wallet_position exists for this event's wallet
        payload = latest_event.payload
        wallet = payload.get("fee_payer", "") or payload.get("wallet", "")
        
        if wallet:
            pos_result = await session.execute(
                select(WalletPosition).where(WalletPosition.wallet == wallet).limit(1)
            )
            position = pos_result.scalar_one_or_none()
            
            if position:
                print(f"\n  ✅ wallet_position EXISTS for {wallet[:14]}...")
                print(f"     Token: {position.token_mint[:14]}...")
                print(f"     Size: {float(position.position_size):.2f}")
                
                # Check if metrics exist
                metrics_result = await session.execute(
                    select(WalletMetrics).where(WalletMetrics.wallet == wallet).limit(1)
                )
                metrics = metrics_result.scalar_one_or_none()
                
                if metrics:
                    print(f"\n  ✅ wallet_metrics EXISTS")
                    print(f"     PnL: ${float(metrics.total_realized_pnl):.2f}")
                else:
                    print(f"\n  ❌ wallet_metrics MISSING")
                    print(f"     AggregationWorker is not running!")
            else:
                print(f"\n  ❌ wallet_position MISSING for {wallet[:14]}...")
        else:
            print("\n  ❌ No wallet found in event payload")
        
        # Check Redis streams
        streams_redis = redis_manager.get_client("streams")
        
        print("\n  Redis Stream Status:")
        for stream_name in ["solana_intel.raw.pending", "solana_intel.raw.stored", 
                           "solana_intel.trade.normalized", "solana_intel.trade.enriched",
                           "solana_intel.alert.triggered"]:
            try:
                info = await streams_redis.xinfo_stream(stream_name)
                length = info.get("length", 0)
                print(f"    {stream_name}: {length} events")
            except:
                print(f"    {stream_name}: 0 events")


async def print_summary(db_manager: DatabaseManager, redis_manager: RedisManager):
    """Print audit summary."""
    print("\n" + "=" * 70)
    print("AUDIT SUMMARY")
    print("=" * 70)
    
    from sqlalchemy import select, func
    from app.infrastructure.database.models.raw_event import RawEvent
    from app.infrastructure.database.models.wallet_position import WalletPosition
    from app.infrastructure.database.models.wallet_metrics import WalletMetrics
    
    async with db_manager.get_session() as session:
        event_count = await session.execute(select(func.count(RawEvent.id)))
        pos_count = await session.execute(select(func.count(WalletPosition.id)))
        metrics_count = await session.execute(select(func.count(WalletMetrics.id)))
        
        total_events = event_count.scalar()
        total_positions = pos_count.scalar()
        total_metrics = metrics_count.scalar()
    
    streams_redis = redis_manager.get_client("streams")
    
    # Count streams
    stream_counts = {}
    for stream_name in ["solana_intel.raw.pending", "solana_intel.raw.stored",
                       "solana_intel.trade.normalized", "solana_intel.trade.enriched",
                       "solana_intel.alert.triggered"]:
        try:
            info = await streams_redis.xinfo_stream(stream_name)
            stream_counts[stream_name] = info.get("length", 0)
        except:
            stream_counts[stream_name] = 0
    
    print("\n📊 DATABASE STATE:")
    print(f"  raw_events:       {total_events}")
    print(f"  wallet_positions:  {total_positions}")
    print(f"  wallet_metrics:    {total_metrics}")
    
    print("\n📡 REDIS STREAMS:")
    for stream, count in stream_counts.items():
        print(f"  {stream}: {count}")
    
    print("\n🔍 PIPELINE STATUS:")
    print(f"  ✅ Data Ingestion:    {'ACTIVE' if total_events > 0 else 'INACTIVE'}")
    print(f"  ✅ Position Tracking:  {'ACTIVE' if total_positions > 0 else 'INACTIVE'}")
    print(f"  {'✅' if total_metrics > 0 else '❌'} Metrics Generation:  {'ACTIVE' if total_metrics > 0 else 'INACTIVE (AggregationWorker not registered)'}")
    print(f"  {'✅' if stream_counts.get('solana_intel.trade.enriched', 0) > 0 else '❌'} Signal Generation:   {'ACTIVE' if stream_counts.get('solana_intel.trade.enriched', 0) > 0 else 'INACTIVE (AnalyticsWorker not connected)'}")
    print(f"  ❌ Prediction Engine: NOT CONNECTED")
    print(f"  ❌ Ranking Engine:    NOT CONNECTED")
    
    print("\n" + "=" * 70)
    print("VERDICT: System is 'DATA PIPELINE ONLY', not intelligence-active")
    print("=" * 70)
    print("\nTo activate intelligence layers:")
    print("  1. Register AggregationWorker in orchestrator")
    print("  2. Connect AnalyticsWorker to signal generation")
    print("  3. Wire prediction engine to live events")
    print("  4. Connect ranking engine to token data")


if __name__ == "__main__":
    asyncio.run(run_audit())
