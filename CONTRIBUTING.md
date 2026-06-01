# Contributing

## Development Setup

1. Clone the repository
2. Copy `.env.example` to `.env`
3. Run `docker compose up -d`
4. Run `docker compose exec api alembic upgrade head`

## Code Style

- Python 3.12+
- Type hints required
- Async-first for all I/O
- No ML/RL frameworks

## Testing

```bash
# Run all tests
python -m pytest tests/

# Run specific test suite
python scripts/test_helius_webhook_failover.py
```

## Pull Requests

1. Create feature branch from `main`
2. Add tests for new functionality
3. Ensure all tests pass
4. Update documentation if needed
5. Submit PR with clear description

## Security

- Never commit secrets (`.env`, `config/api_keys.json`)
- Use environment variables for sensitive data
- Report security issues privately
