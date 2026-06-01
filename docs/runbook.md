# Alert Thresholds & Operational Runbook

## Alert Thresholds

### Critical (Page immediately)

```yaml
alerts:
  - name: worker_down
    condition: up{job="worker"} == 0
    duration: 1m
    severity: critical
    action: Restart worker container

  - name: dlq_growing
    condition: rate(solana_intel_event_dlq_total[5m]) > 10
    duration: 5m
    severity: critical
    action: Check parser health, review DLQ entries

  - name: db_pool_exhausted
    condition: solana_intel_db_pool_size{state="checkedout"} > 18
    duration: 2m
    severity: critical
    action: Check for slow queries, increase pool size

  - name: stream_depth_critical
    condition: solana_intel_stream_depth > 50000
    duration: 5m
    severity: critical
    action: Scale workers, check for bottlenecks
```

### Warning (Notify)

```yaml
alerts:
  - name: high_retry_rate
    condition: rate(solana_intel_event_retries_total[5m]) > 5
    duration: 5m
    severity: warning
    action: Review error patterns, check dependencies

  - name: price_stale
    condition: solana_intel_pricing_freshness_seconds > 600
    duration: 10m
    severity: warning
    action: Check Jupiter API, verify network connectivity

  - name: worker_error_rate
    condition: rate(solana_intel_worker_errors_total[5m]) > 1
    duration: 5m
    severity: warning
    action: Review worker logs, check for data issues

  - name: stream_depth_warning
    condition: solana_intel_stream_depth > 10000
    duration: 10m
    severity: warning
    action: Monitor growth rate, prepare scaling

  - name: db_latency_high
    condition: histogram_quantile(0.95, rate(solana_intel_db_write_seconds[5m])) > 0.5
    duration: 5m
    severity: warning
    action: Check for lock contention, optimize queries
```

## Operational Runbook

### 1. Worker Down

**Symptoms:**
- `up{job="worker"} == 0`
- Events not being processed
- Stream depth increasing

**Diagnosis:**
```bash
# Check worker logs
docker logs solana_intel_worker --tail 100

# Check worker status
docker ps | grep worker

# Check Redis connectivity
docker exec solana_intel_redis redis-cli ping
```

**Resolution:**
```bash
# Restart worker
docker compose restart worker

# If persistent, check resource usage
docker stats solana_intel_worker
```

### 2. DLQ Growing

**Symptoms:**
- `rate(solana_intel_event_dlq_total[5m]) > 10`
- Events failing repeatedly

**Diagnosis:**
```bash
# Check DLQ contents
docker exec solana_intel_redis redis-cli xrange solana_intel.dead_letter - + COUNT 10

# Check parser logs for errors
docker logs solana_intel_worker --tail 100 | grep "parser.*error"

# Check event structure
docker exec solana_intel_redis redis-cli xrange solana_intel.raw.pending - + COUNT 1
```

**Resolution:**
1. Identify failing event type
2. Check parser logic for new edge cases
3. Fix parser and replay DLQ events
4. Consider increasing max_retries for transient failures

### 3. Stream Depth Increasing

**Symptoms:**
- `solana_intel_stream_depth > 10000`
- Consumer lag increasing

**Diagnosis:**
```bash
# Check stream depth
docker exec solana_intel_redis redis-cli xlen solana_intel.raw.pending

# Check consumer lag
docker exec solana_intel_redis redis-cli xpending solana_intel.raw.pending ingestion

# Check worker throughput
curl -s http://localhost:8000/metrics | grep "solana_intel_events_total"
```

**Resolution:**
1. Scale workers: `docker compose up -d --scale worker=3`
2. Check for slow processing in workers
3. Consider increasing concurrency setting

### 4. Price Stale

**Symptoms:**
- `solana_intel_pricing_freshness_seconds > 600`
- Unrealized PnL calculations outdated

**Diagnosis:**
```bash
# Check pricing worker logs
docker logs solana_intel_worker --tail 50 | grep "pricing"

# Check Jupiter API availability
curl -s "https://api.jup.ag/price/v2?ids=So11111111111111111111111111111111111111112" | head -c 200

# Check Redis cache
docker exec solana_intel_redis redis-cli keys "price:*" | head -20
```

**Resolution:**
1. Check Jupiter API status page
2. Verify network connectivity
3. Check pricing worker logs for errors
4. Manually trigger price refresh if needed

### 5. DB Connection Pool Exhausted

**Symptoms:**
- `solana_intel_db_pool_size{state="checkedout"} > 18`
- Slow query responses
- Connection timeouts

**Diagnosis:**
```bash
# Check active connections
docker exec solana_intel_postgres psql -U solana_intel -d solana_wallet_intel -c \
  "SELECT count(*) FROM pg_stat_activity;"

# Check slow queries
docker exec solana_intel_postgres psql -U solana_intel -d solana_wallet_intel -c \
  "SELECT pid, now() - pg_stat_activity.query_start AS duration, query \
   FROM pg_stat_activity \
   WHERE (now() - pg_stat_activity.query_start) > interval '5 seconds';"
```

**Resolution:**
1. Kill long-running queries
2. Add indexes for slow queries
3. Increase pool size in settings
4. Consider read replicas for analytics queries

## Emergency Procedures

### Full System Reset

```bash
# Stop all services
docker compose down

# Clear Redis (WARNING: loses all data)
docker compose down -v

# Restart
docker compose up -d

# Run migrations
docker compose exec api alembic upgrade head
```

### Replay DLQ Events

```python
# Script to replay DLQ events
import asyncio
from app.infrastructure.redis.streams import StreamsManager
from redis.asyncio import Redis

async def replay_dlq():
    redis = Redis.from_url("redis://localhost:6379/1")
    streams = StreamsManager(redis)
    
    # Read DLQ events
    events = await redis.xrange("solana_intel.dead_letter", count=100)
    
    for event_id, data in events:
        # Republish to original stream
        original_stream = data.get("dlq_original_stream")
        if original_stream:
            await streams.append(original_stream, data)
            await redis.xack("solana_intel.dead_letter", "dlq-processor", event_id)
            print(f"Replayed {event_id} to {original_stream}")

asyncio.run(replay_dlq())
```

### Scale Workers

```bash
# Scale to 3 workers
docker compose up -d --scale worker=3

# Check worker distribution
docker compose ps worker
```

## Monitoring Checklist

- [ ] Prometheus scraping metrics endpoint
- [ ] Grafana dashboards configured
- [ ] Alert rules configured in Alertmanager
- [ ] PagerDuty/OpsGenie integration
- [ ] Log aggregation (ELK/Datadog)
- [ ] Distributed tracing (Jaeger/Zipkin)
- [ ] Uptime monitoring (Pingdom/UptimeRobot)
