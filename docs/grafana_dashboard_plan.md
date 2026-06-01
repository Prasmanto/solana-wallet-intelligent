# Grafana Dashboard Plan — Solana Wallet Intelligence Platform

## Dashboard Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  SOLANA WALLET INTEL - OPERATIONS DASHBOARD                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐    │
│  │  Event Pipeline  │  │  Worker Health   │  │  Parser Stats   │    │
│  │  ──────────────  │  │  ──────────────  │  │  ──────────────  │    │
│  │  Events/sec      │  │  Worker Uptime   │  │  Parse/sec      │    │
│  │  Stream Depth    │  │  Concurrency     │  │  Success Rate   │    │
│  │  Consumer Lag    │  │  Error Rate      │  │  Latency p95    │    │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘    │
│                                                                     │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐    │
│  │  Pricing Health  │  │  DLQ Monitoring  │  │  DB Performance │    │
│  │  ──────────────  │  │  ──────────────  │  │  ──────────────  │    │
│  │  Price Freshness │  │  DLQ Depth       │  │  Write Latency  │    │
│  │  Cache Hit Rate  │  │  Retry Rate      │  │  Pool Size      │    │
│  │  Fetch Success   │  │  Error Types     │  │  Query Latency  │    │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Dashboard Panels

### 1. Event Pipeline Dashboard

| Panel | Metric | Type | Query |
|---|---|---|---|
| Events/sec | `solana_intel_events_total` | Rate | `rate(solana_intel_events_total[5m])` |
| Stream Depth | `solana_intel_stream_depth` | Gauge | `solana_intel_stream_depth` |
| Consumer Lag | `solana_intel_consumer_lag` | Gauge | `solana_intel_consumer_lag` |
| Event Latency | `solana_intel_event_processing_seconds` | Histogram | `histogram_quantile(0.95, ...)` |
| Retry Rate | `solana_intel_event_retries_total` | Rate | `rate(solana_intel_event_retries_total[5m])` |
| DLQ Rate | `solana_intel_event_dlq_total` | Rate | `rate(solana_intel_event_dlq_total[5m])` |

### 2. Worker Health Dashboard

| Panel | Metric | Type | Query |
|---|---|---|---|
| Worker Uptime | `solana_intel_worker_uptime_seconds` | Gauge | `solana_intel_worker_uptime_seconds` |
| Worker Concurrency | `solana_intel_worker_concurrency` | Gauge | `solana_intel_worker_concurrency` |
| Worker Errors | `solana_intel_worker_errors_total` | Rate | `rate(solana_intel_worker_errors_total[5m])` |
| Error by Type | `solana_intel_worker_errors_total` | Bar | `sum by (error_type) (rate(...))` |

### 3. Parser Dashboard

| Panel | Metric | Type | Query |
|---|---|---|---|
| Parse/sec | `solana_intel_parser_success_total` | Rate | `rate(solana_intel_parser_success_total[5m])` |
| Success Rate | `solana_intel_parser_success_total` | Gauge | `success / (success + failure)` |
| Parse Latency | `solana_intel_parser_duration_seconds` | Histogram | `histogram_quantile(0.95, ...)` |
| Failures by Code | `solana_intel_parser_failure_total` | Bar | `sum by (error_code) (rate(...))` |

### 4. Pricing Dashboard

| Panel | Metric | Type | Query |
|---|---|---|---|
| Price Freshness | `solana_intel_pricing_freshness_seconds` | Gauge | `solana_intel_pricing_freshness_seconds` |
| Fetch Rate | `solana_intel_pricing_fetch_total` | Rate | `rate(solana_intel_pricing_fetch_total[5m])` |
| Cache Hit Rate | `solana_intel_pricing_cache_hits_total` | Gauge | `hits / total_fetches` |
| Stale Prices | `solana_intel_pricing_freshness_seconds > 300` | Alert | `count(...)` |

### 5. DLQ Monitoring Dashboard

| Panel | Metric | Type | Query |
|---|---|---|---|
| DLQ Depth | `solana_intel_event_dlq_total` | Counter | `sum(solana_intel_event_dlq_total)` |
| DLQ by Reason | `solana_intel_event_dlq_total` | Bar | `sum by (reason) (rate(...))` |
| DLQ Growth Rate | `solana_intel_event_dlq_total` | Rate | `rate(solana_intel_event_dlq_total[1h])` |
| Retry Success Rate | Retries / Total | Gauge | `1 - (dlq / total_events)` |

### 6. DB Performance Dashboard

| Panel | Metric | Type | Query |
|---|---|---|---|
| Write Latency | `solana_intel_db_write_seconds` | Histogram | `histogram_quantile(0.95, ...)` |
| Read Latency | `solana_intel_db_read_seconds` | Histogram | `histogram_quantile(0.95, ...)` |
| Pool Size | `solana_intel_db_pool_size` | Gauge | `solana_intel_db_pool_size` |
| Active Connections | Pool checked out | Gauge | `solana_intel_db_pool_size{state="checkedout"}` |

## Alert Rules

### Critical Alerts (Page immediately)

| Alert | Condition | Duration |
|---|---|---|
| Worker Down | `up{job="worker"} == 0` | 1m |
| DLQ Growing | `rate(solana_intel_event_dlq_total[5m]) > 10` | 5m |
| DB Connection Pool Exhausted | `solana_intel_db_pool_size{state="checkedout"} > 18` | 2m |
| Stream Depth Critical | `solana_intel_stream_depth > 50000` | 5m |

### Warning Alerts (Notify)

| Alert | Condition | Duration |
|---|---|---|
| High Retry Rate | `rate(solana_intel_event_retries_total[5m]) > 5` | 5m |
| Price Stale | `solana_intel_pricing_freshness_seconds > 600` | 10m |
| Worker Error Rate | `rate(solana_intel_worker_errors_total[5m]) > 1` | 5m |
| Stream Depth Warning | `solana_intel_stream_depth > 10000` | 10m |
| DB Latency High | `histogram_quantile(0.95, rate(solana_intel_db_write_seconds[5m])) > 0.5` | 5m |

### Info Alerts (Log only)

| Alert | Condition |
|---|---|
| Worker Restart | `up{job="worker"} == 1` after being 0 |
| DLQ Processed | `solana_intel_event_dlq_total` decreases |
| Price Refresh Complete | `solana_intel_pricing_fetch_total` increments |
