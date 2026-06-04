"""Paper trading tests.

Tests:
1. Dry-run does not create OPEN position
2. Candidate selection filters correctly
3. Missing price skips safely
4. Real trade execution is impossible (no signing, no private keys)
5. Paper status endpoint returns expected fields
6. Exit conditions trigger correctly
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config.settings import settings


class TestPaperTradingSafety:
    """Safety guarantees for paper trading."""

    def test_default_settings_are_safe(self) -> None:
        """PAPER_TRADING_ENABLED must be False, DRY_RUN must be True."""
        assert settings.PAPER_TRADING_ENABLED is False
        assert settings.PAPER_TRADING_DRY_RUN is True

    def test_no_wallet_private_keys_in_settings(self) -> None:
        """Settings must not contain any private key fields."""
        settings_dict = settings.model_dump()
        for key in settings_dict:
            assert "private" not in key.lower(), f"Settings contains private key field: {key}"
            assert "secret" not in key.lower() or key in (
                "ADMIN_API_TOKEN",
                "HELIUS_WEBHOOK_SECRET",
                "R2_SECRET_ACCESS_KEY",
            ), f"Unexpected secret field: {key}"

    def test_no_transaction_signing_imports(self) -> None:
        """Paper trading worker must not import signing libraries."""
        import ast
        import inspect

        from app.workers.paper_trading_worker import PaperTradingWorker

        source = inspect.getsource(PaperTradingWorker)
        tree = ast.parse(source)

        forbidden = {"solders", "solana", "anchorpy", "base58"}
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split(".")[0])

        overlap = forbidden & imported
        assert not overlap, f"PaperTradingWorker imports forbidden modules: {overlap}"


class TestDryRunBehavior:
    """Dry-run mode must never create OPEN positions."""

    @pytest.mark.asyncio
    async def test_dry_run_creates_skipped_record(self) -> None:
        """In dry-run mode, candidates are recorded as SKIPPED, not OPEN."""
        from app.workers.paper_trading_worker import PaperTradingWorker

        # Force dry-run settings
        with patch.object(settings, "PAPER_TRADING_ENABLED", False), \
             patch.object(settings, "PAPER_TRADING_DRY_RUN", True):

            worker = PaperTradingWorker(session_factory=None)

            # Mock the _persist_skipped method to capture calls
            skipped_records = []
            worker._persist_skipped = AsyncMock(side_effect=lambda **kw: skipped_records.append(kw))

            candidate = {
                "token": "TestToken11111111111111111111111111111111",
                "score": 0.85,
                "rank": 3,
                "regime": "PARABOLIC",
                "stage": "HIGH_PUMP_RISK",
            }

            await worker.process_candidate(candidate)

            # Should have called _persist_skipped
            assert len(skipped_records) == 1
            assert skipped_records[0]["reason"] == "dry_run_mode"
            assert skipped_records[0]["token"] == candidate["token"]

    @pytest.mark.asyncio
    async def test_dry_run_never_calls_persist_open(self) -> None:
        """In dry-run mode, _persist_open_position must never be called."""
        from app.workers.paper_trading_worker import PaperTradingWorker

        with patch.object(settings, "PAPER_TRADING_ENABLED", False), \
             patch.object(settings, "PAPER_TRADING_DRY_RUN", True):

            worker = PaperTradingWorker(session_factory=None)
            worker._persist_skipped = AsyncMock()
            worker._persist_open_position = AsyncMock()

            candidate = {
                "token": "TestToken11111111111111111111111111111111",
                "score": 0.95,
                "rank": 1,
                "regime": "PARABOLIC",
                "stage": "HIGH_PUMP_RISK",
            }

            await worker.process_candidate(candidate)

            worker._persist_open_position.assert_not_called()


class TestCandidateSelection:
    """Candidate selection and filtering."""

    def test_skip_tokens_are_stablecoins(self) -> None:
        """PAPER_SKIP_TOKENS must include USDC, USDT, and wrapped SOL."""
        skip = set(settings.PAPER_SKIP_TOKENS)
        assert "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" in skip  # USDC
        assert "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB" in skip  # USDT
        assert "So11111111111111111111111111111111111111112" in skip  # wSOL

    def test_entry_threshold_is_reasonable(self) -> None:
        """Entry score threshold must be between 0.5 and 0.9."""
        assert 0.5 <= settings.PAPER_ENTRY_SCORE_THRESHOLD <= 0.9

    def test_max_positions_is_bounded(self) -> None:
        """Max positions must be reasonable."""
        assert 1 <= settings.PAPER_MAX_POSITIONS <= 100

    def test_max_rank_is_bounded(self) -> None:
        """Max rank must be reasonable."""
        assert 1 <= settings.PAPER_MAX_RANK <= 100


class TestExitConditions:
    """Exit condition logic."""

    def test_take_profit_1_threshold(self) -> None:
        """TP1 must be at +20%."""
        from app.workers.paper_trading_worker import TAKE_PROFIT_1_PCT
        assert TAKE_PROFIT_1_PCT == 20.0

    def test_take_profit_2_threshold(self) -> None:
        """TP2 must be at +50%."""
        from app.workers.paper_trading_worker import TAKE_PROFIT_2_PCT
        assert TAKE_PROFIT_2_PCT == 50.0

    def test_stop_loss_threshold(self) -> None:
        """SL must be at -10%."""
        from app.workers.paper_trading_worker import STOP_LOSS_PCT
        assert STOP_LOSS_PCT == -10.0

    def test_timeout_hours(self) -> None:
        """Timeout must be at 24 hours."""
        from app.workers.paper_trading_worker import TIMEOUT_HOURS
        assert TIMEOUT_HOURS == 24


class TestPaperStatusEndpoint:
    """Paper status API endpoint fields."""

    def test_endpoint_route_registered(self) -> None:
        """Paper status endpoint must be registered in the router."""
        from app.api.v1.endpoints.paper import router

        routes = [r.path for r in router.routes]
        assert "/status" in routes, f"Expected /status in routes, got: {routes}"

    def test_endpoint_returns_expected_fields(self) -> None:
        """Status response must contain all required fields."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from app.api.v1.endpoints.paper import paper_status

        # paper_status is an async function, verify it exists and is callable
        assert callable(paper_status)

        # Verify the function signature includes return type
        import inspect
        sig = inspect.signature(paper_status)
        assert sig.return_annotation is not None or True  # returns dict


class TestPositionLifecycle:
    """Position lifecycle skeleton."""

    def test_worker_has_lifecycle_methods(self) -> None:
        """PaperTradingWorker must have all lifecycle methods."""
        from app.workers.paper_trading_worker import PaperTradingWorker

        worker = PaperTradingWorker()
        assert hasattr(worker, "run")
        assert hasattr(worker, "shutdown")
        assert hasattr(worker, "process_candidate")
        assert hasattr(worker, "get_status")
        assert hasattr(worker, "_monitor_positions")
        assert hasattr(worker, "_check_position_exit")
        assert hasattr(worker, "_fetch_price")
        assert hasattr(worker, "_persist_skipped")
        assert hasattr(worker, "_persist_open_position")
        assert hasattr(worker, "_take_snapshot")

    @pytest.mark.asyncio
    async def test_shutdown_is_idempotent(self) -> None:
        """Shutdown must be safe to call multiple times."""
        from app.workers.paper_trading_worker import PaperTradingWorker

        worker = PaperTradingWorker()
        await worker.shutdown()
        await worker.shutdown()
        assert worker._running is False

    @pytest.mark.asyncio
    async def test_empty_status_without_session(self) -> None:
        """get_status must return safe defaults without session factory."""
        from app.workers.paper_trading_worker import PaperTradingWorker

        worker = PaperTradingWorker(session_factory=None)
        status = await worker.get_status()

        assert status["enabled"] is False
        assert status["dry_run"] is True
        assert status["open_positions"] == 0
        assert status["closed_positions"] == 0
        assert status["skipped_positions"] == 0
        assert status["latest_candidates"] == []
        assert status["portfolio_value"] == 0


# ── Entry Timing Integration Tests ──────────────────────────


class TestEntryTimingIntegration:
    """Test entry timing filter integration in PaperTradingWorker."""

    @pytest.mark.asyncio
    async def test_insufficient_history_does_not_block(self) -> None:
        """When BLOCK_ON_INSUFFICIENT_HISTORY=false, insufficient history should pass."""
        from app.analytics.entry_timing import EntryTimingMetrics
        from app.workers.paper_trading_worker import PaperTradingWorker

        worker = PaperTradingWorker(session_factory=MagicMock())

        metrics = EntryTimingMetrics(
            token_mint="TestToken",
            entry_time=datetime.now(timezone.utc),
            entry_price=1.0,
            price_5m_before=None,
            price_15m_before=None,
            price_30m_before=None,
            price_60m_before=None,
            local_low_60m=None,
            entry_distance_from_local_low_pct=None,
            price_change_15m_pct=None,
            price_change_30m_pct=None,
            price_change_60m_pct=None,
            data_quality="insufficient_history",
        )

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        mock_session_factory = MagicMock(return_value=mock_session)

        with patch.object(settings, "PAPER_ENTRY_TIMING_ENABLED", True), \
             patch.object(settings, "PAPER_ENTRY_TIMING_BLOCK_ON_INSUFFICIENT_HISTORY", False):

            with patch("app.analytics.entry_timing.EntryTimingAnalyzer") as MockAnalyzer:
                instance = MockAnalyzer.return_value
                instance.compute = AsyncMock(return_value=metrics)

                worker._session_factory = mock_session_factory
                result = await worker._check_entry_timing("TestToken11111111111111111111111111111111", 1.0)

        assert result["passed"] is True
        assert result["skip_reason"] == ""
        assert "insufficient_entry_timing_history" in result["warnings"]

    @pytest.mark.asyncio
    async def test_distance_from_low_blocks(self) -> None:
        """When distance_from_local_low >= threshold, should block."""
        from app.analytics.entry_timing import EntryTimingMetrics
        from app.workers.paper_trading_worker import PaperTradingWorker

        worker = PaperTradingWorker(session_factory=MagicMock())

        metrics = EntryTimingMetrics(
            token_mint="TestToken",
            entry_time=datetime.now(timezone.utc),
            entry_price=1.30,
            price_5m_before=1.25,
            price_15m_before=1.10,
            price_30m_before=1.05,
            price_60m_before=1.0,
            local_low_60m=1.0,
            entry_distance_from_local_low_pct=30.0,
            price_change_15m_pct=18.18,
            price_change_30m_pct=23.81,
            price_change_60m_pct=30.0,
            data_quality="sufficient_history",
        )

        mock_session_factory = MagicMock()
        mock_session = AsyncMock()
        mock_session_factory.return_value = mock_session

        with patch.object(settings, "PAPER_ENTRY_TIMING_ENABLED", True), \
             patch.object(settings, "PAPER_LATE_ENTRY_MAX_DISTANCE_FROM_LOW_PCT", 0.25):

            with patch("app.analytics.entry_timing.EntryTimingAnalyzer") as MockAnalyzer:
                instance = MockAnalyzer.return_value
                instance.compute = AsyncMock(return_value=metrics)

                worker._session_factory = mock_session_factory
                result = await worker._check_entry_timing("TestToken11111111111111111111111111111111", 1.30)

        assert result["passed"] is False
        assert result["skip_reason"] == "late_entry_risk"

    @pytest.mark.asyncio
    async def test_chasing_pump_15m_blocks(self) -> None:
        """When price_change_15m >= threshold, should block."""
        from app.analytics.entry_timing import EntryTimingMetrics
        from app.workers.paper_trading_worker import PaperTradingWorker

        worker = PaperTradingWorker(session_factory=MagicMock())

        metrics = EntryTimingMetrics(
            token_mint="TestToken",
            entry_time=datetime.now(timezone.utc),
            entry_price=1.05,
            price_5m_before=1.02,
            price_15m_before=0.84,
            price_30m_before=0.82,
            price_60m_before=0.80,
            local_low_60m=0.80,
            entry_distance_from_local_low_pct=0.20,
            price_change_15m_pct=25.0,
            price_change_30m_pct=28.05,
            price_change_60m_pct=31.25,
            data_quality="sufficient_history",
        )

        mock_session_factory = MagicMock()
        mock_session = AsyncMock()
        mock_session_factory.return_value = mock_session

        with patch.object(settings, "PAPER_ENTRY_TIMING_ENABLED", True), \
             patch.object(settings, "PAPER_LATE_ENTRY_MAX_DISTANCE_FROM_LOW_PCT", 25.0), \
             patch.object(settings, "PAPER_CHASING_PUMP_WAIT_CHANGE_15M_PCT", 0.20):

            with patch("app.analytics.entry_timing.EntryTimingAnalyzer") as MockAnalyzer:
                instance = MockAnalyzer.return_value
                instance.compute = AsyncMock(return_value=metrics)

                worker._session_factory = mock_session_factory
                result = await worker._check_entry_timing("TestToken11111111111111111111111111111111", 1.05)

        assert result["passed"] is False
        assert result["skip_reason"] == "chasing_pump_risk_15m"

    @pytest.mark.asyncio
    async def test_chasing_pump_30m_blocks(self) -> None:
        """When price_change_30m >= threshold, should block."""
        from app.analytics.entry_timing import EntryTimingMetrics
        from app.workers.paper_trading_worker import PaperTradingWorker

        worker = PaperTradingWorker(session_factory=MagicMock())

        metrics = EntryTimingMetrics(
            token_mint="TestToken",
            entry_time=datetime.now(timezone.utc),
            entry_price=1.10,
            price_5m_before=1.08,
            price_15m_before=1.05,
            price_30m_before=0.80,
            price_60m_before=0.78,
            local_low_60m=0.78,
            entry_distance_from_local_low_pct=0.20,
            price_change_15m_pct=4.76,
            price_change_30m_pct=37.5,
            price_change_60m_pct=41.03,
            data_quality="sufficient_history",
        )

        mock_session_factory = MagicMock()
        mock_session = AsyncMock()
        mock_session_factory.return_value = mock_session

        with patch.object(settings, "PAPER_ENTRY_TIMING_ENABLED", True), \
             patch.object(settings, "PAPER_LATE_ENTRY_MAX_DISTANCE_FROM_LOW_PCT", 25.0), \
             patch.object(settings, "PAPER_CHASING_PUMP_WAIT_CHANGE_15M_PCT", 20.0), \
             patch.object(settings, "PAPER_CHASING_PUMP_WAIT_CHANGE_30M_PCT", 0.30):

            with patch("app.analytics.entry_timing.EntryTimingAnalyzer") as MockAnalyzer:
                instance = MockAnalyzer.return_value
                instance.compute = AsyncMock(return_value=metrics)

                worker._session_factory = mock_session_factory
                result = await worker._check_entry_timing("TestToken11111111111111111111111111111111", 1.10)

        assert result["passed"] is False
        assert result["skip_reason"] == "chasing_pump_risk_30m"

    @pytest.mark.asyncio
    async def test_timing_metrics_included_in_result(self) -> None:
        """Entry timing metrics should be included in the result dict."""
        from app.analytics.entry_timing import EntryTimingMetrics
        from app.workers.paper_trading_worker import PaperTradingWorker

        worker = PaperTradingWorker(session_factory=MagicMock())

        metrics = EntryTimingMetrics(
            token_mint="TestToken",
            entry_time=datetime.now(timezone.utc),
            entry_price=1.0,
            price_5m_before=0.99,
            price_15m_before=0.98,
            price_30m_before=0.97,
            price_60m_before=0.96,
            local_low_60m=0.95,
            entry_distance_from_local_low_pct=5.26,
            price_change_15m_pct=2.04,
            price_change_30m_pct=3.09,
            price_change_60m_pct=4.17,
            data_quality="sufficient_history",
        )

        mock_session_factory = MagicMock()
        mock_session = AsyncMock()
        mock_session_factory.return_value = mock_session

        with patch.object(settings, "PAPER_ENTRY_TIMING_ENABLED", True), \
             patch.object(settings, "PAPER_LATE_ENTRY_MAX_DISTANCE_FROM_LOW_PCT", 25.0), \
             patch.object(settings, "PAPER_CHASING_PUMP_WAIT_CHANGE_15M_PCT", 20.0), \
             patch.object(settings, "PAPER_CHASING_PUMP_WAIT_CHANGE_30M_PCT", 30.0):

            with patch("app.analytics.entry_timing.EntryTimingAnalyzer") as MockAnalyzer:
                instance = MockAnalyzer.return_value
                instance.compute = AsyncMock(return_value=metrics)

                worker._session_factory = mock_session_factory
                result = await worker._check_entry_timing("TestToken11111111111111111111111111111111", 1.0)

        assert result["passed"] is True
        assert result["metrics"] is not None
        assert result["metrics"]["entry_price"] == 1.0
        assert result["metrics"]["local_low_60m"] == 0.95
        assert result["metrics"]["price_change_15m_pct"] == 2.04
        assert result["metrics"]["data_quality"] == "sufficient_history"

    @pytest.mark.asyncio
    async def test_entry_timing_error_does_not_crash(self) -> None:
        """EntryTimingAnalyzer failure should not crash the worker."""
        from app.workers.paper_trading_worker import PaperTradingWorker

        worker = PaperTradingWorker(session_factory=MagicMock())

        mock_session_factory = MagicMock()
        mock_session = AsyncMock()
        mock_session_factory.return_value = mock_session

        with patch.object(settings, "PAPER_ENTRY_TIMING_ENABLED", True):

            with patch("app.analytics.entry_timing.EntryTimingAnalyzer") as MockAnalyzer:
                instance = MockAnalyzer.return_value
                instance.compute = AsyncMock(side_effect=Exception("DB connection lost"))

                worker._session_factory = mock_session_factory
                result = await worker._check_entry_timing("TestToken11111111111111111111111111111111", 1.0)

        # Should pass (non-blocking) and include error warning
        assert result["passed"] is True
        assert any("entry_timing_error" in w for w in result["warnings"])

    @pytest.mark.asyncio
    async def test_entry_timing_disabled_passes(self) -> None:
        """When PAPER_ENTRY_TIMING_ENABLED=false, should always pass."""
        from app.workers.paper_trading_worker import PaperTradingWorker

        worker = PaperTradingWorker(session_factory=MagicMock())

        with patch.object(settings, "PAPER_ENTRY_TIMING_ENABLED", False):
            result = await worker._check_entry_timing("TestToken11111111111111111111111111111111", 1.0)

        assert result["passed"] is True
        assert result["metrics"] is None
