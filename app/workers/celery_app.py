"""Workers module - Celery application and task definitions.

Responsibilities:
- Define Celery app with Redis broker
- Periodic tasks (re-sync, analytics refresh)
- Async task queue for ingestion pipeline
"""

from __future__ import annotations

from celery import Celery

from app.config import settings

celery_app = Celery(
    "solana_wallet_intel",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Auto-discover tasks from workers module
celery_app.autodiscover_tasks(["app.workers"])
