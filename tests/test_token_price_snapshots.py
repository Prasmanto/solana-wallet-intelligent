"""Token price snapshot tests.

Tests:
1. ORM model structure
2. Repository insert batch with dedup
3. Repository queries (latest, range, nearest_before)
4. Repository retention cleanup
5. Price snapshot service capture
6. Price snapshot service missing price skip
7. Entry timing with insufficient history
8. Entry timing with synthetic history
9. Worker integration does not crash if snapshot fails
10. Throttle/dedup behavior
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config.settings import settings


def _mock_session() -> MagicMock:
    """Create a mock AsyncSession where add() is sync (MagicMock).

    SQLAlchemy AsyncSession.add() is synchronous. Using AsyncMock for it
    produces unawaited coroutine warnings.
    """
    session = AsyncMock()
    session.add = MagicMock()
    return session


# ── ORM Model Tests ─────────────────────────────────────────


class TestTokenPriceSnapshotModel:
    """Test the ORM model structure."""

    def test_model_table_name(self) -> None:
        """Table name must be token_price_snapshots."""
        from app.infrastructure.database.models.token_price_snapshot import (
            TokenPriceSnapshot,
        )

        assert TokenPriceSnapshot.__tablename__ == "token_price_snapshots"

    def test_model_required_columns(self) -> None:
        """All required columns must exist."""
        from app.infrastructure.database.models.token_price_snapshot import (
            TokenPriceSnapshot,
        )

        required = [
            "id", "token_mint", "price", "source", "confidence",
            "context", "fetched_at", "created_at",
        ]
        for col in required:
            assert hasattr(TokenPriceSnapshot, col), f"Missing column: {col}"

    def test_model_nullable_columns(self) -> None:
        """slot and metadata_json should be nullable."""
        from app.infrastructure.database.models.token_price_snapshot import (
            TokenPriceSnapshot,
        )

        assert hasattr(TokenPriceSnapshot, "slot")
        assert hasattr(TokenPriceSnapshot, "metadata_json")

    def test_model_has_repr(self) -> None:
        """Model should have __repr__."""
        from app.infrastructure.database.models.token_price_snapshot import (
            TokenPriceSnapshot,
        )

        assert hasattr(TokenPriceSnapshot, "__repr__")

    def test_model_context_default(self) -> None:
        """Context should have server_default of 'scheduled'."""
        from app.infrastructure.database.models.token_price_snapshot import (
            TokenPriceSnapshot,
        )

        col = TokenPriceSnapshot.context
        assert col.property.columns[0].server_default.arg == "scheduled"


# ── Repository Tests ────────────────────────────────────────


class TestPriceSnapshotRepository:
    """Test repository insert/query operations."""

    @pytest.mark.asyncio
    async def test_insert_batch_empty(self) -> None:
        """Inserting empty list should return 0."""
        from app.infrastructure.database.repositories.price_snapshot_repo import (
            PriceSnapshotRepository,
        )

        mock_session = _mock_session()
        repo = PriceSnapshotRepository(mock_session)
        result = await repo.insert_batch([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_insert_batch_single(self) -> None:
        """Inserting a single snapshot should succeed."""
        from app.infrastructure.database.repositories.price_snapshot_repo import (
            PriceSnapshotRepository,
        )

        mock_session = _mock_session()
        # Mock the dedup check to return 0 (no existing)
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_session.execute.return_value = mock_result

        repo = PriceSnapshotRepository(mock_session)
        now = datetime.now(timezone.utc)
        snapshots = [
            {
                "token_mint": "TestToken11111111111111111111111111111111",
                "price": 1.5,
                "source": "jupiter",
                "confidence": 1.0,
                "fetched_at": now,
                "context": "scheduled",
            }
        ]

        result = await repo.insert_batch(snapshots)
        assert result == 1
        mock_session.add.assert_called_once()
        mock_session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_insert_batch_dedup_skips_existing(self) -> None:
        """Should skip snapshots that already exist within dedup window."""
        from app.infrastructure.database.repositories.price_snapshot_repo import (
            PriceSnapshotRepository,
        )

        mock_session = _mock_session()
        # Mock dedup check to return 1 (existing snapshot found)
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1
        mock_session.execute.return_value = mock_result

        repo = PriceSnapshotRepository(mock_session)
        now = datetime.now(timezone.utc)
        snapshots = [
            {
                "token_mint": "TestToken11111111111111111111111111111111",
                "price": 1.5,
                "source": "jupiter",
                "fetched_at": now,
            }
        ]

        result = await repo.insert_batch(snapshots)
        assert result == 0
        mock_session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_insert_batch_multiple_with_mixed_dedup(self) -> None:
        """Should insert only non-duplicate snapshots."""
        from app.infrastructure.database.repositories.price_snapshot_repo import (
            PriceSnapshotRepository,
        )

        mock_session = _mock_session()
        # First call: dedup returns 0 (new), second call: returns 1 (exists)
        mock_result_new = MagicMock()
        mock_result_new.scalar.return_value = 0
        mock_result_exists = MagicMock()
        mock_result_exists.scalar.return_value = 1
        mock_session.execute.side_effect = [mock_result_new, mock_result_exists]

        repo = PriceSnapshotRepository(mock_session)
        now = datetime.now(timezone.utc)
        snapshots = [
            {
                "token_mint": "Token1111111111111111111111111111111111111",
                "price": 1.5,
                "source": "jupiter",
                "fetched_at": now,
            },
            {
                "token_mint": "Token2222222222222222222222222222222222222",
                "price": 2.0,
                "source": "jupiter",
                "fetched_at": now,
            },
        ]

        result = await repo.insert_batch(snapshots)
        assert result == 1
        mock_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_before_returns_zero_for_empty(self) -> None:
        """Deleting with no matching rows should return 0."""
        from app.infrastructure.database.repositories.price_snapshot_repo import (
            PriceSnapshotRepository,
        )

        mock_session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_session.execute.return_value = mock_result

        repo = PriceSnapshotRepository(mock_session)
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        result = await repo.delete_before(cutoff)
        assert result == 0


# ── Price Snapshot Service Tests ────────────────────────────


class TestPriceSnapshotService:
    """Test the service layer for snapshot capture."""

    @pytest.mark.asyncio
    async def test_capture_empty_mints_returns_zero(self) -> None:
        """Should return 0 for empty mint list."""
        from app.analytics.price_snapshot_service import PriceSnapshotService

        mock_pricing = AsyncMock()
        service = PriceSnapshotService(mock_pricing)
        mock_session = AsyncMock()

        result = await service.capture_snapshots(mock_session, [])
        assert result == 0

    @pytest.mark.asyncio
    async def test_capture_skips_unavailable_prices(self) -> None:
        """Should skip tokens with no price data."""
        from app.analytics.price_snapshot_service import PriceSnapshotService

        mock_pricing = AsyncMock()
        mock_pricing.get_batch_prices.return_value = {}
        service = PriceSnapshotService(mock_pricing)
        mock_session = AsyncMock()

        result = await service.capture_snapshots(
            mock_session,
            ["TestToken11111111111111111111111111111111"],
        )
        assert result == 0

    @pytest.mark.asyncio
    async def test_capture_does_not_raise_on_fetch_error(self) -> None:
        """Should swallow fetch errors and return 0."""
        from app.analytics.price_snapshot_service import PriceSnapshotService

        mock_pricing = AsyncMock()
        mock_pricing.get_batch_prices.side_effect = Exception("Jupiter down")
        service = PriceSnapshotService(mock_pricing)
        mock_session = AsyncMock()

        result = await service.capture_snapshots(
            mock_session,
            ["TestToken11111111111111111111111111111111"],
        )
        assert result == 0

    @pytest.mark.asyncio
    async def test_capture_does_not_raise_on_insert_error(self) -> None:
        """Should swallow insert errors and return 0."""
        from app.analytics.price_snapshot_service import PriceSnapshotService
        from app.schemas.pricing import TokenPrice

        mock_pricing = AsyncMock()
        mock_pricing.get_batch_prices.return_value = {
            "TestToken": TokenPrice(
                mint="TestToken",
                price=Decimal("1.5"),
                source="jupiter",
                fetched_at=datetime.now(timezone.utc),
            ),
        }
        service = PriceSnapshotService(mock_pricing)

        mock_session = AsyncMock()
        mock_session.execute.side_effect = Exception("DB error")

        result = await service.capture_snapshots(
            mock_session,
            ["TestToken"],
        )
        assert result == 0

    @pytest.mark.asyncio
    async def test_capture_deduplicates_mints(self) -> None:
        """Should deduplicate mints before fetching."""
        from app.analytics.price_snapshot_service import PriceSnapshotService

        mock_pricing = AsyncMock()
        mock_pricing.get_batch_prices.return_value = {}
        service = PriceSnapshotService(mock_pricing)
        mock_session = AsyncMock()

        await service.capture_snapshots(
            mock_session,
            ["Token1", "Token1", "Token1"],
        )

        # Should call with unique mints only
        call_args = mock_pricing.get_batch_prices.call_args[0][0]
        assert len(call_args) == 1

    @pytest.mark.asyncio
    async def test_retention_does_not_raise_on_error(self) -> None:
        """Retention should swallow errors."""
        from app.analytics.price_snapshot_service import PriceSnapshotService

        mock_pricing = AsyncMock()
        service = PriceSnapshotService(mock_pricing)

        mock_session = AsyncMock()
        mock_session.execute.side_effect = Exception("DB error")

        result = await service.run_retention(mock_session)
        assert result == 0


# ── Entry Timing Tests ──────────────────────────────────────


class TestEntryTimingAnalyzer:
    """Test entry timing metrics computation."""

    @pytest.mark.asyncio
    async def test_insufficient_history(self) -> None:
        """Should return insufficient_history when few snapshots exist."""
        from app.analytics.entry_timing import EntryTimingAnalyzer

        mock_session = AsyncMock()
        # Mock empty result (no snapshots)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        analyzer = EntryTimingAnalyzer(mock_session)
        now = datetime.now(timezone.utc)

        metrics = await analyzer.compute(
            token_mint="TestToken11111111111111111111111111111111",
            entry_time=now,
            entry_price=1.5,
        )

        assert metrics.data_quality == "insufficient_history"
        assert metrics.price_5m_before is None
        assert metrics.price_15m_before is None
        assert metrics.local_low_60m is None
        assert metrics.price_change_15m_pct is None

    @pytest.mark.asyncio
    async def test_sufficient_history_with_synthetic_data(self) -> None:
        """Should compute metrics correctly with enough snapshots."""
        from app.analytics.entry_timing import EntryTimingAnalyzer
        from app.infrastructure.database.models.token_price_snapshot import (
            TokenPriceSnapshot,
        )

        now = datetime.now(timezone.utc)

        # Create synthetic snapshots at various offsets
        snapshots = []
        for minutes_ago in [55, 45, 30, 20, 15, 10, 5, 2]:
            snap = MagicMock(spec=TokenPriceSnapshot)
            snap.fetched_at = now - timedelta(minutes=minutes_ago)
            snap.price = 1.0 + (minutes_ago * 0.01)  # Price increases going back
            snapshots.append(snap)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = snapshots
        mock_session.execute.return_value = mock_result

        analyzer = EntryTimingAnalyzer(mock_session)
        entry_price = 1.02  # Close to current

        metrics = await analyzer.compute(
            token_mint="TestToken11111111111111111111111111111111",
            entry_time=now,
            entry_price=entry_price,
        )

        assert metrics.data_quality == "sufficient_history"
        assert metrics.price_5m_before is not None
        assert metrics.price_15m_before is not None
        assert metrics.local_low_60m is not None
        assert metrics.entry_price == entry_price

    @pytest.mark.asyncio
    async def test_entry_distance_from_local_low(self) -> None:
        """Should compute distance from local low correctly."""
        from app.analytics.entry_timing import EntryTimingAnalyzer
        from app.infrastructure.database.models.token_price_snapshot import (
            TokenPriceSnapshot,
        )

        now = datetime.now(timezone.utc)

        # Create snapshots with known prices
        snapshots = []
        prices = [0.8, 0.9, 1.0, 1.1]
        for i, price in enumerate(prices):
            snap = MagicMock(spec=TokenPriceSnapshot)
            snap.fetched_at = now - timedelta(minutes=(30 - i * 5))
            snap.price = price
            snapshots.append(snap)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = snapshots
        mock_session.execute.return_value = mock_result

        analyzer = EntryTimingAnalyzer(mock_session)

        metrics = await analyzer.compute(
            token_mint="TestToken11111111111111111111111111111111",
            entry_time=now,
            entry_price=1.0,
        )

        # local_low = 0.8, entry = 1.0
        # distance = (1.0 - 0.8) / 0.8 * 100 = 25%
        assert metrics.local_low_60m == 0.8
        assert metrics.entry_distance_from_local_low_pct is not None
        assert abs(metrics.entry_distance_from_local_low_pct - 25.0) < 0.01

    @pytest.mark.asyncio
    async def test_price_change_computation(self) -> None:
        """Should compute price changes correctly."""
        from app.analytics.entry_timing import EntryTimingAnalyzer
        from app.infrastructure.database.models.token_price_snapshot import (
            TokenPriceSnapshot,
        )

        now = datetime.now(timezone.utc)

        # Create snapshots at specific offsets
        # 15m ago: price 1.0, now: price 1.1 => 10% change
        snapshots = []
        for minutes_ago, price in [(60, 0.9), (30, 0.95), (15, 1.0), (5, 1.05)]:
            snap = MagicMock(spec=TokenPriceSnapshot)
            snap.fetched_at = now - timedelta(minutes=minutes_ago)
            snap.price = price
            snapshots.append(snap)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = snapshots
        mock_session.execute.return_value = mock_result

        analyzer = EntryTimingAnalyzer(mock_session)

        metrics = await analyzer.compute(
            token_mint="TestToken11111111111111111111111111111111",
            entry_time=now,
            entry_price=1.1,
        )

        # price_15m = 1.0, entry = 1.1 => 10% change
        assert metrics.price_change_15m_pct is not None
        assert abs(metrics.price_change_15m_pct - 10.0) < 0.01

    @pytest.mark.asyncio
    async def test_metrics_to_dict(self) -> None:
        """to_dict should serialize all fields."""
        from app.analytics.entry_timing import EntryTimingMetrics

        now = datetime.now(timezone.utc)
        metrics = EntryTimingMetrics(
            token_mint="TestToken",
            entry_time=now,
            entry_price=1.0,
            price_5m_before=0.95,
            price_15m_before=0.90,
            price_30m_before=0.85,
            price_60m_before=0.80,
            local_low_60m=0.80,
            entry_distance_from_local_low_pct=25.0,
            price_change_15m_pct=11.11,
            price_change_30m_pct=17.65,
            price_change_60m_pct=25.0,
            data_quality="sufficient_history",
        )

        d = metrics.to_dict()
        assert d["token_mint"] == "TestToken"
        assert d["entry_price"] == 1.0
        assert d["price_5m_before"] == 0.95
        assert d["local_low_60m"] == 0.80
        assert d["data_quality"] == "sufficient_history"
        assert "entry_time" in d

    def test_change_computation_with_none(self) -> None:
        """Change should be None if either price is None."""
        from app.analytics.entry_timing import EntryTimingAnalyzer

        assert EntryTimingAnalyzer._compute_change(None, 1.0) is None
        assert EntryTimingAnalyzer._compute_change(1.0, None) is None
        assert EntryTimingAnalyzer._compute_change(None, None) is None

    def test_change_computation_with_zero_earlier(self) -> None:
        """Change should be None if earlier price is zero."""
        from app.analytics.entry_timing import EntryTimingAnalyzer

        assert EntryTimingAnalyzer._compute_change(0, 1.0) is None

    def test_change_computation_normal(self) -> None:
        """Change should compute percentage correctly."""
        from app.analytics.entry_timing import EntryTimingAnalyzer

        result = EntryTimingAnalyzer._compute_change(1.0, 1.1)
        assert result is not None
        assert abs(result - 10.0) < 0.01


# ── Worker Integration Tests ────────────────────────────────


class TestWorkerSnapshotIntegration:
    """Test that snapshot failures don't crash workers."""

    @pytest.mark.asyncio
    async def test_paper_worker_snapshot_failure_is_non_fatal(self) -> None:
        """PaperTradingWorker should not crash if snapshot fails."""
        from app.workers.paper_trading_worker import PaperTradingWorker

        worker = PaperTradingWorker(session_factory=None)

        # _capture_open_position_snapshots should handle None gracefully
        await worker._capture_open_position_snapshots()

    @pytest.mark.asyncio
    async def test_paper_worker_should_price_snapshot_disabled(self) -> None:
        """Should return True for time check regardless of enabled flag (guard is in lifecycle)."""
        from app.workers.paper_trading_worker import PaperTradingWorker

        worker = PaperTradingWorker()
        now = datetime.now(timezone.utc)

        # _should_price_snapshot only checks time interval, not enabled flag
        # The enabled guard is in _lifecycle_cycle which checks self._snapshot_service
        assert worker._should_price_snapshot(now) is True

    @pytest.mark.asyncio
    async def test_paper_worker_should_price_snapshot_first_time(self) -> None:
        """Should return True on first cycle."""
        from app.workers.paper_trading_worker import PaperTradingWorker

        worker = PaperTradingWorker()
        now = datetime.now(timezone.utc)

        with patch.object(settings, "PRICE_SNAPSHOT_ENABLED", True):
            assert worker._should_price_snapshot(now) is True

    @pytest.mark.asyncio
    async def test_paper_worker_should_price_snapshot_throttle(self) -> None:
        """Should throttle based on interval."""
        from app.workers.paper_trading_worker import PaperTradingWorker

        worker = PaperTradingWorker()
        now = datetime.now(timezone.utc)

        with patch.object(settings, "PRICE_SNAPSHOT_ENABLED", True), \
             patch.object(settings, "PRICE_SNAPSHOT_INTERVAL_SECONDS", 300):

            # Set last snapshot to 1 minute ago
            worker._last_price_snapshot = now - timedelta(minutes=1)
            assert worker._should_price_snapshot(now) is False

            # Set last snapshot to 6 minutes ago
            worker._last_price_snapshot = now - timedelta(minutes=6)
            assert worker._should_price_snapshot(now) is True

    @pytest.mark.asyncio
    async def test_paper_worker_capture_candidate_no_session(self) -> None:
        """Should handle no session factory gracefully."""
        from app.workers.paper_trading_worker import PaperTradingWorker

        worker = PaperTradingWorker(session_factory=None)
        worker._snapshot_service = AsyncMock()

        # Should not raise
        await worker._capture_candidate_snapshot(
            "TestToken",
            {"score": 0.8, "rank": 1},
        )

    @pytest.mark.asyncio
    async def test_paper_worker_capture_candidate_no_service(self) -> None:
        """Should handle no snapshot service gracefully."""
        from app.workers.paper_trading_worker import PaperTradingWorker

        worker = PaperTradingWorker(session_factory=lambda: AsyncMock())
        worker._snapshot_service = None

        # Should not raise
        await worker._capture_candidate_snapshot(
            "TestToken",
            {"score": 0.8, "rank": 1},
        )

    def test_paper_worker_has_snapshot_attributes(self) -> None:
        """Worker should have snapshot-related attributes."""
        from app.workers.paper_trading_worker import PaperTradingWorker

        worker = PaperTradingWorker()
        assert hasattr(worker, "_snapshot_service")
        assert hasattr(worker, "_last_price_snapshot")
        assert hasattr(worker, "_should_price_snapshot")
        assert hasattr(worker, "_capture_candidate_snapshot")
        assert hasattr(worker, "_capture_open_position_snapshots")
        assert hasattr(worker, "_run_snapshot_retention")

    def test_ranking_worker_has_snapshot_attributes(self) -> None:
        """Ranking worker should have snapshot-related attributes."""
        from app.workers.ranking_worker import RankingWorker

        # Can't instantiate without redis, just check class exists
        assert hasattr(RankingWorker, "_capture_ranked_token_snapshots")


# ── Settings Tests ──────────────────────────────────────────


class TestPriceSnapshotSettings:
    """Test settings defaults."""

    def test_snapshot_enabled_default(self) -> None:
        """PRICE_SNAPSHOT_ENABLED should default to True."""
        assert settings.PRICE_SNAPSHOT_ENABLED is True

    def test_snapshot_interval_default(self) -> None:
        """PRICE_SNAPSHOT_INTERVAL_SECONDS should default to 300."""
        assert settings.PRICE_SNAPSHOT_INTERVAL_SECONDS == 300

    def test_snapshot_retention_default(self) -> None:
        """PRICE_SNAPSHOT_RETENTION_DAYS should default to 7."""
        assert settings.PRICE_SNAPSHOT_RETENTION_DAYS == 7

    def test_snapshot_top_ranked_limit_default(self) -> None:
        """PRICE_SNAPSHOT_TOP_RANKED_LIMIT should default to 50."""
        assert settings.PRICE_SNAPSHOT_TOP_RANKED_LIMIT == 50

    def test_snapshot_dedup_window_default(self) -> None:
        """PRICE_SNAPSHOT_DEDUP_WINDOW_SECONDS should default to 120."""
        assert settings.PRICE_SNAPSHOT_DEDUP_WINDOW_SECONDS == 120


# ── Migration Tests ─────────────────────────────────────────


class TestMigrationStructure:
    """Test migration file structure."""

    def test_migration_file_exists(self) -> None:
        """Migration file should exist."""
        import os
        migration_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "alembic",
            "versions",
            "010_create_token_price_snapshots.py",
        )
        assert os.path.exists(migration_path)

    def test_migration_revision_chain(self) -> None:
        """Migration should chain from 009_paper_trading."""
        import importlib.util
        import os

        migration_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "alembic",
            "versions",
            "010_create_token_price_snapshots.py",
        )
        spec = importlib.util.spec_from_file_location("migration", migration_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert module.revision == "010_token_price_snapshots"
        assert module.down_revision == "009_paper_trading"
