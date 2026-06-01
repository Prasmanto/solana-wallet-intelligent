# Solana Wallet Intel

Real-time Solana wallet intelligence platform. Ingests blockchain events via Helius webhooks, normalizes transactions, tracks wallet positions, computes metrics, and predicts pump activity.

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
| `/metrics` | GET | - | Prometheus metrics |

## Helius Webhook Failover

The system supports multiple Helius API keys from different accounts. When one account's credits are exhausted, the system automatically creates a webhook on the next available account.

**Config:** `config/api_keys.json` (not committed, see `.gitignore`)

**Dashboard:** Compact provider card shows current provider, health, events/hr, and failover count.

## Project Structure

```
app/
├── api/v1/endpoints/    # FastAPI route handlers
├── config/              # Settings, metrics, API key manager
├── core/domain/         # Stream names, domain models
├── infrastructure/
│   ├── database/        # SQLAlchemy models, migrations
│   ├── helius/          # Webhook failover, API client
│   ├── redis/           # Stream management
│   └── external/        # Jupiter price client
├── parser/              # Helius event parser
├── analytics/           # Metrics, pricing, features
├── workers/             # Pipeline workers
└── services/            # Business logic
```

## Monitoring

- **Dashboard:** `http://localhost:8000/api/v1/dashboard` (auto-refresh 30s)
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

## Safety Notice

This repository is a sanitized public version. Production secrets, API keys, deployment scripts, and private infrastructure configuration are intentionally excluded. See [SECURITY.md](SECURITY.md) for details.

## License

MIT License
