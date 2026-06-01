"""Production Health and Data Flow Audit Script.

Run this on VPS to verify system status.

Usage:
    python -m scripts.production_health_audit
    OR
    docker compose exec api python -m scripts.production_health_audit
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger(__name__)


async def run_audit():
    """Run complete production health audit."""
    print("\n" + "=" * 70)
    print("PRODUCTION HEALTH AND DATA FLOW AUDIT")
    print("=" * 70)
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 70)
    
    try:
        from app.config.settings import settings
        from app.infrastructure.database.manager import DatabaseManager
        from app.infrastructure.redis.manager import RedisManager
        
        db_manager = DatabaseManager(settings)
        redis_manager = RedisManager(settings)
        
        await db_manager.connect()
        await redis_manager.connect()
        
        # 1. Check Database Counts
        await check_database_counts(db_manager)
        
        # 2. Check Latest Activity
        await check_latest_activity(db_manager)
        
        # 3. Check Pipeline Flow
        await check_pipeline_flow(db_manager, redis_manager)
        
        # 4. Check Real-Time Activity
        await check_realtime_activity(db_manager)
        
        # 5. Print Summary
        await print_summary(db_manager, redis_manager)
        
        await db_manager.close()
        await redis_manager.close()
        
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()


async def check_database_counts(db_manager):
    """Check database counts for all tables."""
    print("\n" + "-" * 70)
    print("1. DATABASE COUNTS")
    print("-" * 70)
    
    from sqlalchemy import select, func, text
    
    async with db_manager.get_session() as session:
        tables = [
            ("raw_events", "raw_events"),
            ("wallet_positions", "wallet_positions"),
            ("wallet_metrics", "wallet_metrics"),
            ("wallet_features", "wallet_features"),
            ("predictions", "predictions"),
        ]
        
        print(f"\n{'Table':<25} {'Count':<10} {'Status'}")
        print("-" * 50)
        
        for table_name, table_class_name in tables:
            try:
                # Use raw SQL for reliability
                result = await session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                count = result.scalar()
                
                # Determine status
                if count == 0:
                    status = "EMPTY"
                elif count < 10:
                    status = "LOW"
                elif count < 100:
                    status = "MODERATE"
                else:
                    status = "GOOD"
                
                print(f"{table_name:<25} {count:<10} {status}")
                
            except Exception as e:
                print(f"{table_name:<25} {'ERROR':<10} {str(e)[:30]}")


async def check_latest_activity(db_manager):
    """Check latest activity timestamps."""
    print("\n" + "-" * 70)
    print("2. LATEST ACTIVITY")
    print("-" * 70)
    
    from sqlalchemy import text
    
    async with db_manager.get_session() as session:
        tables = [
            ("raw_events", "created_at"),
            ("wallet_positions", "last_processed_at"),
            ("wallet_metrics", "last_updated_at"),
            ("wallet_features", "computed_at"),
            ("predictions", "created_at"),
        ]
        
        print(f"\n{'Table':<25} {'Latest Activity':<25} {'Status'}")
        print("-" * 65)
        
        for table_name, timestamp_col in tables:
            try:
                result = await session.execute(
                    text(f"SELECT MAX({timestamp_col}) FROM {table_name}")
                )
                latest = result.scalar()
                
                if latest:
                    # Calculate age
                    now = datetime.now(timezone.utc)
                    if hasattr(latest, 'tzinfo') and latest.tzinfo is None:
                        latest = latest.replace(tzinfo=timezone.utc)
                    
                    age = now - latest
                    age_str = str(age).split('.')[0]  # Remove microseconds
                    
                    if age.total_seconds() < 3600:  # < 1 hour
                        status = "RECENT"
                    elif age.total_seconds() < 86400:  # < 1 day
                        status = "STALE"
                    else:
                        status = "OLD"
                    
                    print(f"{table_name:<25} {str(latest)[:25]:<25} {status}")
                else:
                    print(f"{table_name:<25} {'NO DATA':<25} EMPTY")
                    
            except Exception as e:
                print(f"{table_name:<25} {'ERROR':<25} {str(e)[:20]}")


async def check_pipeline_flow(db_manager, redis_manager):
    """Check if events are flowing through the pipeline."""
    print("\n" + "-" * 70)
    print("3. PIPELINE FLOW")
    print("-" * 70)
    
    from sqlalchemy import text
    streams_redis = redis_manager.get_client("streams")
    
    # Check Redis streams
    streams = [
        "solana_intel.raw.pending",
        "solana_intel.raw.stored",
        "solana_intel.trade.normalized",
        "solana_intel.trade.enriched",
        "solana_intel.aggregated.features",
        "solana_intel.predictions",
        "solana_intel.rankings",
        "solana_intel.alert.triggered",
    ]
    
    print(f"\n{'Stream':<40} {'Length':<10} {'Status'}")
    print("-" * 60)
    
    stream_counts = {}
    for stream in streams:
        try:
            info = await streams_redis.xinfo_stream(stream)
            length = info.get("length", 0)
            stream_counts[stream] = length
            
            if length == 0:
                status = "EMPTY"
            elif length < 10:
                status = "LOW"
            elif length < 100:
                status = "MODERATE"
            else:
                status = "GOOD"
            
            print(f"{stream:<40} {length:<10} {status}")
            
        except Exception as e:
            print(f"{stream:<40} {'0':<10} NOT EXISTS")
            stream_counts[stream] = 0
    
    # Check pipeline bottlenecks
    print("\nPIPELINE BOTTLENECK ANALYSIS:")
    print("-" * 60)
    
    bottlenecks = []
    
    if stream_counts.get("solana_intel.raw.pending", 0) > 0:
        bottlenecks.append("raw.pending has pending events")
    
    if stream_counts.get("solana_intel.raw.stored", 0) > 0:
        bottlenecks.append("raw.stored has unprocessed events")
    
    if stream_counts.get("solana_intel.trade.normalized", 0) > 0:
        bottlenecks.append("trade.normalized has unprocessed events")
    
    if stream_counts.get("solana_intel.trade.enriched", 0) > 0:
        bottlenecks.append("trade.enriched has unprocessed events")
    
    if stream_counts.get("solana_intel.aggregated.features", 0) > 0:
        bottlenecks.append("aggregated.features has unprocessed events")
    
    if stream_counts.get("solana_intel.predictions", 0) > 0:
        bottlenecks.append("predictions has unprocessed events")
    
    if bottlenecks:
        for b in bottlenecks:
            print(f"  ⚠️  {b}")
    else:
        print("  ✅ No bottlenecks detected")


async def check_realtime_activity(db_manager):
    """Check real-time activity."""
    print("\n" + "-" * 70)
    print("4. REAL-TIME ACTIVITY")
    print("-" * 70)
    
    from sqlalchemy import text
    
    async with db_manager.get_session() as session:
        # Check for events in last hour
        result = await session.execute(text("""
            SELECT COUNT(*) FROM raw_events 
            WHERE created_at > NOW() - INTERVAL '1 hour'
        """))
        recent_events = result.scalar()
        
        # Check for positions created in last hour
        result = await session.execute(text("""
            SELECT COUNT(*) FROM wallet_positions 
            WHERE last_processed_at > NOW() - INTERVAL '1 hour'
        """))
        recent_positions = result.scalar()
        
        # Check for predictions created in last hour
        result = await session.execute(text("""
            SELECT COUNT(*) FROM predictions 
            WHERE created_at > NOW() - INTERVAL '1 hour'
        """))
        recent_predictions = result.scalar()
        
        print(f"\nActivity in last hour:")
        print(f"  Raw events:      {recent_events}")
        print(f"  Wallet positions: {recent_positions}")
        print(f"  Predictions:     {recent_predictions}")
        
        # Determine activity level
        if recent_events > 0 or recent_positions > 0 or recent_predictions > 0:
            print(f"\n  ✅ System is ACTIVE")
        else:
            print(f"\n  ⚠️  System has NO recent activity")


async def print_summary(db_manager, redis_manager):
    """Print audit summary."""
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    from sqlalchemy import text
    streams_redis = redis_manager.get_client("streams")
    
    # Get counts
    async with db_manager.get_session() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM raw_events"))
        raw_count = result.scalar()
        
        result = await session.execute(text("SELECT COUNT(*) FROM wallet_positions"))
        pos_count = result.scalar()
        
        result = await session.execute(text("SELECT COUNT(*) FROM wallet_metrics"))
        metrics_count = result.scalar()
        
        result = await session.execute(text("SELECT COUNT(*) FROM predictions"))
        pred_count = result.scalar()
    
    # Get stream counts
    stream_counts = {}
    for stream in ["solana_intel.raw.pending", "solana_intel.trade.enriched", 
                   "solana_intel.aggregated.features", "solana_intel.predictions"]:
        try:
            info = await streams_redis.xinfo_stream(stream)
            stream_counts[stream] = info.get("length", 0)
        except:
            stream_counts[stream] = 0
    
    print(f"\nDATABASE STATE:")
    print(f"  raw_events:       {raw_count}")
    print(f"  wallet_positions:  {pos_count}")
    print(f"  wallet_metrics:    {metrics_count}")
    print(f"  predictions:       {pred_count}")
    
    print(f"\nREDIS STREAMS:")
    for stream, count in stream_counts.items():
        print(f"  {stream}: {count}")
    
    # Determine system status
    print(f"\nSYSTEM STATUS:")
    
    if raw_count > 0 and pos_count > 0 and metrics_count > 0 and pred_count > 0:
        print("  ✅ FULLY ACTIVE - All layers processing")
    elif raw_count > 0 and pos_count > 0:
        print("  ⚠️  PARTIALLY ACTIVE - Data pipeline only, no intelligence")
    elif raw_count > 0:
        print("  ⚠️  INGESTION ONLY - Events received but not processed")
    else:
        print("  ❌ IDLE - No data in system")
    
    # Check for bottlenecks
    pending = stream_counts.get("solana_intel.raw.pending", 0)
    enriched = stream_counts.get("solana_intel.trade.enriched", 0)
    
    if pending > 0:
        print(f"\n  ⚠️  BOTTLENECK: {pending} events pending in raw.pending")
    if enriched > 0:
        print(f"\n  ⚠️  BOTTLENECK: {enriched} events pending in trade.enriched")


if __name__ == "__main__":
    asyncio.run(run_audit())
