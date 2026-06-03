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

    # ── Ranking ─────────────────────────────────────────────
    RANKING_RETENTION_HOURS: int = 24
    RANKING_WINDOW_MINUTES: int = 5
    RANKING_MAX_TOKENS: int = 100

    # ── Paper Trading ───────────────────────────────────────
    PAPER_TRADING_ENABLED: bool = False
    PAPER_TRADING_DRY_RUN: bool = True
    PAPER_POSITION_SIZE_USD: float = 100.0
    PAPER_MAX_POSITIONS: int = 20
    PAPER_ENTRY_SCORE_THRESHOLD: float = 0.65
    PAPER_MAX_RANK: int = 20
    PAPER_SNAPSHOT_INTERVAL_SECONDS: int = 300
    PAPER_VIRTUAL_CAPITAL: float = 100000.0
    PAPER_RISK_PER_TRADE: float = 0.01
    PAPER_SKIP_TOKENS: list[str] = Field(
        default=[
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
            "So11111111111111111111111111111111111111112",      # Wrapped SOL
        ],
    )
    PAPER_MAX_TOKEN_ACTIVITY_AGE_MINUTES: int = 30
    PAPER_MIN_TOKEN_EVENTS_15M: int = 10
    PAPER_MIN_UNIQUE_WALLETS_15M: int = 5

    # ── Price Snapshots ────────────────────────────────────
    PRICE_SNAPSHOT_ENABLED: bool = True
    PRICE_SNAPSHOT_INTERVAL_SECONDS: int = 300  # 5 min
    PRICE_SNAPSHOT_RETENTION_DAYS: int = 7
    PRICE_SNAPSHOT_TOP_RANKED_LIMIT: int = 50
    PRICE_SNAPSHOT_DEDUP_WINDOW_SECONDS: int = 120

    # ── Jupiter Price API ──────────────────────────────────
    JUPITER_PRICE_BASE_URL: str = "https://lite-api.jup.ag/price/v3"

    # ── Redis Streams Retention ────────────────────────────
    REDIS_STREAM_MAXLEN: int = 10000


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
