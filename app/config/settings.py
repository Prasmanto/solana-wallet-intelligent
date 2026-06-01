from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Priority: .env file > environment variables > defaults.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────
    APP_NAME: str = "Solana Wallet Intel"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    SERVICE_ROLE: Literal["api", "worker"] = "api"

    # ── PostgreSQL ───────────────────────────────────────────
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "solana_intel"
    POSTGRES_PASSWORD: str = "dev_password"
    POSTGRES_DB: str = "solana_wallet_intel"

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def DATABASE_URL_SYNC(self) -> str:
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ── Redis ────────────────────────────────────────────────
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0

    # Separate DBs for stream isolation
    REDIS_STREAMS_DB: int = 1
    REDIS_CACHE_DB: int = 2

    @property
    def REDIS_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def REDIS_STREAMS_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_STREAMS_DB}"

    @property
    def REDIS_CACHE_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_CACHE_DB}"

    # ── Solana RPC ───────────────────────────────────────────
    SOLANA_RPC_URL: str = "https://api.mainnet-beta.solana.com"
    SOLANA_WS_URL: str = "wss://api.mainnet-beta.solana.com"

    # ── API ──────────────────────────────────────────────────
    API_PORT: int = 8000
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: list[str] = Field(default=["http://localhost:3000"])

    # ── Helius Webhook ──────────────────────────────────────
    HELIUS_WEBHOOK_SECRET: str = ""
    HELIUS_API_KEY: str = ""

    # ── Helius Webhook Failover ─────────────────────────────
    HELIUS_FAILOVER_ENABLED: bool = True
    HELIUS_FAILOVER_STALE_THRESHOLD: int = 1800  # seconds (30 min)
    HELIUS_FAILOVER_MULTI_WEBHOOK_MODE: bool = False
    HELIUS_FAILOVER_HEALTH_CHECK_INTERVAL: int = 300  # seconds

    # ── Admin Auth ──────────────────────────────────────────
    ADMIN_API_TOKEN: str = ""

    # ── Cloudflare R2 ──────────────────────────────────────
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = "solana-wallet-intel"
    R2_ENDPOINT_URL: str = ""

    @property
    def R2_S3_ENDPOINT(self) -> str:
        return self.R2_ENDPOINT_URL or f"https://{self.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
