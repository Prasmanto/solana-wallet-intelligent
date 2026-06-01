# Scripts

This directory contains development, testing, and simulation scripts.

Production deployment scripts, VPS-specific utilities, and debug scripts with hardcoded infrastructure are intentionally excluded from this public repository for security reasons.

See [SECURITY.md](../SECURITY.md) for details on what is excluded and why.

## Included Scripts

### Simulation & Testing
- `fake_events.py` — Generate fake Helius webhook events for testing
- `publish_events.py` — Publish test events to Redis Streams
- `simulate_pipeline.py` — Run full pipeline simulation
- `liquidity_burst_simulator.py` — Simulate liquidity burst scenarios
- `run_pump_scenarios.py` — Run pump prediction test scenarios

### Intelligence & Analytics
- `inspect_streams.py` — Inspect Redis Streams contents
- `recompute_wallet_metrics.py` — Recompute wallet metrics from positions
- `live_intelligence_audit.py` — Audit intelligence engine outputs
- `production_health_audit.py` — Check production system health

### Test Suites
- `test_*.py` — Unit and integration tests for various components
