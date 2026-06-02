"""Tests for daily alpha scorecard."""

from __future__ import annotations

import pytest

from app.analytics.daily_scorecard import (
    _compute_verdict,
    _recommended_action,
    render_markdown,
)


class TestVerdictLogic:
    """Test verdict computation."""

    def test_healthy_when_events_and_predictions(self) -> None:
        sections = {
            "pipeline_activity": {"raw_events": 1000, "predictions": 500},
            "signal_activity": {"prediction_count": 500},
            "system_health": {"dlq_count": 0, "failed_events": 0},
            "paper_trading": {"max_drawdown": 0},
        }
        assert _compute_verdict(sections) == "HEALTHY"

    def test_broken_when_no_events(self) -> None:
        sections = {
            "pipeline_activity": {"raw_events": 0, "predictions": 0},
            "signal_activity": {"prediction_count": 0},
            "system_health": {"dlq_count": 0, "failed_events": 0},
            "paper_trading": {"max_drawdown": 0},
        }
        assert _compute_verdict(sections) == "BROKEN"

    def test_broken_when_no_predictions(self) -> None:
        sections = {
            "pipeline_activity": {"raw_events": 1000, "predictions": 0},
            "signal_activity": {"prediction_count": 0},
            "system_health": {"dlq_count": 0, "failed_events": 0},
            "paper_trading": {"max_drawdown": 0},
        }
        assert _compute_verdict(sections) == "BROKEN"

    def test_broken_when_dlq_high(self) -> None:
        sections = {
            "pipeline_activity": {"raw_events": 1000, "predictions": 500},
            "signal_activity": {"prediction_count": 500},
            "system_health": {"dlq_count": 200, "failed_events": 0},
            "paper_trading": {"max_drawdown": 0},
        }
        assert _compute_verdict(sections) == "BROKEN"

    def test_warning_when_dlq_present(self) -> None:
        sections = {
            "pipeline_activity": {"raw_events": 1000, "predictions": 500},
            "signal_activity": {"prediction_count": 500},
            "system_health": {"dlq_count": 5, "failed_events": 0},
            "paper_trading": {"max_drawdown": 0},
        }
        assert _compute_verdict(sections) == "WARNING"

    def test_warning_when_no_predictions_but_events(self) -> None:
        sections = {
            "pipeline_activity": {"raw_events": 1000, "predictions": 100},
            "signal_activity": {"prediction_count": 0},
            "system_health": {"dlq_count": 0, "failed_events": 0},
            "paper_trading": {"max_drawdown": 0},
        }
        assert _compute_verdict(sections) == "WARNING"

    def test_warning_when_deep_drawdown(self) -> None:
        sections = {
            "pipeline_activity": {"raw_events": 1000, "predictions": 500},
            "signal_activity": {"prediction_count": 500},
            "system_health": {"dlq_count": 0, "failed_events": 0},
            "paper_trading": {"max_drawdown": -30},
        }
        assert _compute_verdict(sections) == "WARNING"


class TestRecommendedAction:
    """Test recommended action logic."""

    def test_broken_no_events(self) -> None:
        sections = {
            "verdict": "BROKEN",
            "pipeline_activity": {"raw_events": 0, "predictions": 0},
            "signal_activity": {},
            "paper_trading": {},
            "candidate_filtering": {},
        }
        action = _recommended_action(sections)
        assert "fix_pipeline" in action
        assert "no raw events" in action

    def test_healthy_no_positions(self) -> None:
        sections = {
            "verdict": "HEALTHY",
            "pipeline_activity": {"raw_events": 1000, "predictions": 500},
            "signal_activity": {"prediction_count": 500},
            "paper_trading": {"open_positions": 0},
            "candidate_filtering": {"opened": 0},
        }
        action = _recommended_action(sections)
        assert "enable_next_paper_test" in action

    def test_healthy_with_positions(self) -> None:
        sections = {
            "verdict": "HEALTHY",
            "pipeline_activity": {"raw_events": 1000, "predictions": 500},
            "signal_activity": {"prediction_count": 500},
            "paper_trading": {"open_positions": 1},
            "candidate_filtering": {},
        }
        action = _recommended_action(sections)
        assert "keep_observing" in action


class TestMarkdownRenderer:
    """Test markdown output."""

    def test_contains_required_headings(self) -> None:
        scorecard = {
            "meta": {"generated_at": "2025-01-01T00:00:00", "window_hours": 24},
            "pipeline_activity": {},
            "signal_activity": {"score_buckets": {}, "regime_distribution": {}, "stage_distribution": {},
                                "top_by_score": [], "top_by_count": []},
            "candidate_filtering": {"skip_reasons": {}},
            "paper_trading": {},
            "outcome_quality": {},
            "system_health": {"helius": {}},
            "verdict": "HEALTHY",
            "recommended_action": "keep observing",
        }
        md = render_markdown(scorecard)
        assert "# Daily Alpha Scorecard" in md
        assert "## System Activity" in md
        assert "## Prediction Quality" in md
        assert "## Paper Trading" in md
        assert "## Candidate Filtering" in md
        assert "## Health" in md
        assert "## Verdict" in md
        assert "## Recommended Action" in md

    def test_score_buckets_in_output(self) -> None:
        scorecard = {
            "meta": {"generated_at": "2025-01-01T00:00:00", "window_hours": 24},
            "pipeline_activity": {},
            "signal_activity": {
                "score_buckets": {"0.0-0.2": 10, "0.2-0.4": 20, "0.4-0.6": 30, "0.6-0.8": 40, "0.8-1.0": 50},
                "regime_distribution": {}, "stage_distribution": {},
                "top_by_score": [], "top_by_count": [],
            },
            "candidate_filtering": {"skip_reasons": {}},
            "paper_trading": {},
            "outcome_quality": {},
            "system_health": {"helius": {}},
            "verdict": "HEALTHY",
            "recommended_action": "keep observing",
        }
        md = render_markdown(scorecard)
        assert "0.0-0.2" in md
        assert "0.8-1.0" in md

    def test_skip_reasons_in_output(self) -> None:
        scorecard = {
            "meta": {"generated_at": "2025-01-01T00:00:00", "window_hours": 24},
            "pipeline_activity": {},
            "signal_activity": {"score_buckets": {}, "regime_distribution": {}, "stage_distribution": {},
                                "top_by_score": [], "top_by_count": []},
            "candidate_filtering": {"skip_reasons": {"dry_run_mode": 100, "stale_token_activity": 5}},
            "paper_trading": {},
            "outcome_quality": {},
            "system_health": {"helius": {}},
            "verdict": "HEALTHY",
            "recommended_action": "keep observing",
        }
        md = render_markdown(scorecard)
        assert "dry_run_mode" in md
        assert "stale_token_activity" in md

    def test_empty_scorecard_handled(self) -> None:
        """Empty scorecard should not crash."""
        scorecard = {
            "meta": {},
            "pipeline_activity": {},
            "signal_activity": {},
            "candidate_filtering": {},
            "paper_trading": {},
            "outcome_quality": {},
            "system_health": {},
            "verdict": "UNKNOWN",
            "recommended_action": "",
        }
        md = render_markdown(scorecard)
        assert "# Daily Alpha Scorecard" in md
        assert "UNKNOWN" in md


class TestScorecardSections:
    """Test that generate_scorecard returns all required sections."""

    @pytest.mark.asyncio
    async def test_returns_all_sections(self) -> None:
        """Scorecard must contain all 6 sections plus verdict."""
        from unittest.mock import AsyncMock, MagicMock

        # Mock session
        session = AsyncMock()

        # Mock all execute results to return 0/empty
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_result.fetchall.return_value = []
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        from app.analytics.daily_scorecard import generate_scorecard
        scorecard = await generate_scorecard(session, hours=24)

        required_sections = [
            "pipeline_activity",
            "signal_activity",
            "candidate_filtering",
            "paper_trading",
            "outcome_quality",
            "system_health",
            "verdict",
            "recommended_action",
            "meta",
        ]
        for section in required_sections:
            assert section in scorecard, f"Missing section: {section}"
