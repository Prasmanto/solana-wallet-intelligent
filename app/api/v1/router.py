"""V1 API router — mounts all v1 endpoint routers."""

from fastapi import APIRouter

from app.api.v1.endpoints import health, wallets, webhooks, dashboard, api_keys, helius_webhooks, paper, analytics, system

router = APIRouter()
router.include_router(health.router, prefix="/health", tags=["health"])
router.include_router(wallets.router, prefix="/wallets", tags=["wallets"])
router.include_router(webhooks.router, prefix="/ingest", tags=["ingestion"])
router.include_router(dashboard.router, tags=["dashboard"])
router.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"])
router.include_router(helius_webhooks.router, prefix="/helius", tags=["helius-webhooks"])
router.include_router(paper.router, prefix="/paper", tags=["paper-trading"])
router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
router.include_router(system.router, prefix="/system", tags=["system"])
