# Solana Wallet Intel

Open-source real-time Solana wallet intelligence infrastructure. Ingests blockchain events via Helius webhooks, normalizes transactions, tracks wallet positions, computes metrics, and performs signal ranking experiments for market intelligence research.

## Architecture

```
Helius Webhook → IngestionWorker → ParserWorker → AnalyticsWorker → AggregationWorker → PredictionWorker → RankingWorker → AlertWorker
```

**Stack:** Python 3.12, FastAPI, PostgreSQL, Redis Streams, Docker Compose

## Quick Start

```bash
cp .env.example .env
# Edit .env with your values

docker compose up -d
docker compose exec api alembic upgrade head
```

Dashboard: `http://localhost:8000/api/v1/dashboard`

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTGRES_HOST` | PostgreSQL host | `postgres` |
| `REDIS_HOST` | Redis host | `redis` |
| `HELIUS_API_KEY` | Helius API key | - |
| `ADMIN_API_TOKEN` | Admin auth token | - |

See `.env.example` for full list.

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/v1/health/` | GET | - | Health check |
| `/api/v1/dashboard` | GET | - | Monitoring dashboard |
| `/api/v1/ingest/helius` | POST | - | Helius webhook receiver |
| `/api/v1/api-keys/status` | GET | Admin | API key rotation status |
| `/api/v1/helius/webhooks/status` | GET | Admin | Webhook provider status |
| `/api/v1/helius/webhooks/failover` | POST | Admin | Trigger failover |
| `/api/v1/paper/status` | GET | - | Paper trading portfolio status |
| `/api/v1/analytics/daily-scorecard` | GET | - | Daily alpha scorecard |
| `/api/v1/system/health` | GET | - | VPS system health metrics |
| `/metrics` | GET | - | Prometheus metrics |

## Helius Webhook Failover

The system supports multiple Helius API keys from different accounts. When one account's credits are exhausted, the system automatically creates a webhook on the next available account.

**Config:** `config/api_keys.json` (not committed, see `.gitignore`)

**Dashboard:** Compact provider card shows current provider, health, events/hr, and failover count.

## Daily Alpha Scorecard

Automated daily analytics report covering pipeline activity, signal quality, candidate filtering, paper trading performance, and system health.

```
GET /api/v1/analytics/daily-scorecard?hours=24
GET /api/v1/analytics/daily-scorecard?hours=24&format=markdown
```

**Sections:** Pipeline Activity, Prediction Quality, Candidate Filtering, Paper Trading, Outcome Quality, System Health, Verdict.

## Paper Trading (Dry-Run)

Virtual position simulation for evaluating prediction signals without real capital.

- **Lifecycle:** candidate detection → entry evaluation → position monitoring → TP/SL/timeout exit
- **Safety:** `PAPER_TRADING_DRY_RUN=true` by default — creates SKIPPED records only, never OPEN positions
- **Token activity filter:** validates recent trading activity before entry
- **Exit rules:** +20% TP1, +50% TP2, -10% SL, 24h timeout
- **Trailing stop:** activates at +3% ROI, triggers on 2% drop from peak
- **Parabolic timeout:** 6h max hold for PARABOLIC regime tokens

### Trade Gatekeeper

Multi-layer entry filter before paper position creation:

1. **Stablecoin exclusion** — USDC, USDT, wSOL skipped
2. **Duplicate token guard** — prevents multiple positions on same token
3. **Token activity filter** — requires minimum events and unique wallets within time window
4. **Token momentum filter** — continuous activity-based signal (not binary)
5. **Whale concentration filter** — rejects tokens with top wallet holding >70%
6. **Price availability** — requires valid Jupiter V3 price quote

### Post-Mortem Risk Rules

After each closed trade, the system applies lessons learned:

- **Parabolic entry confirmation** — requires `token_momentum >= 0.30` for PARABOLIC/HIGH_PUMP_RISK tokens
- **Whale concentration guard** — rejects tokens where top wallet holds >70% of tracked supply
- **Trailing stop** — locks in profits after +3% gain (2% drop trigger)
- **Parabolic timeout** — 6h max hold instead of 24h for parabolic tokens

```
GET /api/v1/paper/status
```

## Redis Streams Retention

Redis streams are automatically trimmed to prevent OOM:

- `REDIS_STREAM_MAXLEN=10000` (configurable)
- `maxmemory-policy noeviction` — fails loudly instead of silently evicting
- `maxmemory 2gb` — adjustable based on VPS capacity

## VPS Health Monitoring

Dashboard includes a compact VPS Health card showing CPU, RAM, disk, Redis memory, Postgres size, and container health status.

```
GET /api/v1/system/health
```

## Security Hardening

Production guidance:

- Redis and Postgres should NOT be exposed publicly — use Docker internal network only
- Enable UFW firewall: allow only SSH (22) and API (8000)
- Remove host port mappings for Redis and Postgres from docker-compose
- Rotate API keys and VPS passwords regularly
- See [SECURITY.md](SECURITY.md) for full details

## Project Structure

```
app/
├── api/v1/endpoints/    # FastAPI route handlers
├── config/              # Settings, metrics, API key manager
├── core/domain/         # Stream names, domain models
├── infrastructure/
│   ├── database/        # SQLAlchemy models, migrations
│   ├── helius/          # Webhook failover, API client
│   ├── redis/           # Stream management, price cache
│   └── external/        # Jupiter price client
├── parser/              # Helius event parser
├── analytics/           # Metrics, pricing, features, daily scorecard
├── paper_trading/       # Position management, trade simulation
├── workers/             # Pipeline workers
└── services/            # Business logic
```

## Monitoring

- **Dashboard:** `http://localhost:8000/api/v1/dashboard` (auto-refresh 30s)
  - Helius provider card (failover, keys, events/hr)
  - Paper Trading card (positions, PnL, portfolio value)
  - VPS Health card (CPU, RAM, disk, Redis, containers)
- **Paper Status:** `http://localhost:8000/api/v1/paper/status`
- **Daily Scorecard:** `http://localhost:8000/api/v1/analytics/daily-scorecard`
- **System Health:** `http://localhost:8000/api/v1/system/health`
- **Metrics:** `http://localhost:8000/metrics` (Prometheus format)
- **Logs:** Structured JSON via structlog

## Development

```bash
# Run tests
python -m pytest tests/

# Run specific test
python scripts/test_helius_webhook_failover.py

# Check code style
python -m ruff check app/
```

## Deployment

```bash
# Pull and rebuild
git pull origin main
docker compose build api worker
docker compose up -d api worker

# Run migrations
docker compose exec api alembic upgrade head
```

## Research Roadmap

This project is an evolving research infrastructure. Long-term model design and research notes are tracked in the Notion research roadmap:

**[Solana Wallet Intelligence — Long-Term Model Roadmap](https://app.notion.com/p/Solana-Wallet-Intelligence-Long-Term-Model-Roadmap-e9eb8655a6854c0088757a8dc9b98ce0)**

### Planned Research Areas

- **Trade Gatekeeper** — multi-layer entry filtering with activity, momentum, concentration, and liquidity signals. Currently in paper trading dry-run validation.

- **Exit & Position Manager** — trailing stops, regime-aware timeouts, dynamic position sizing, portfolio-level risk management. Trailing stop and parabolic timeout active in paper trading.

- **Social Intelligence Layer** — future integration of social sentiment, Twitter/Telegram signal correlation, influencer wallet tracking, and narrative detection as additional alpha signals.

These are research directions, not production features. All experiments run in paper trading dry-run mode before any evaluation of real behavior.

## Safety Notice

This repository is a sanitized public version. Production secrets, API keys, deployment scripts, and private infrastructure configuration are intentionally excluded. See [SECURITY.md](SECURITY.md) for details.

This project is research infrastructure for blockchain data engineering and wallet behavior analytics. It is not a trading bot and does not guarantee any financial returns. The paper-trading simulation is for evaluation purposes only.

## License

MIT License
