"""Parser test corpus and validation framework.

Runs all golden tests, validates normalization, and checks for regressions.

Usage:
    python -m tests.run_corpus
    python -m tests.run_corpus --update-snapshots
    python -m tests.run_corpus --protocol jupiter
    python -m tests.run_corpus --verbose
"""

from __future__ import annotations

import asyncio
import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

from app.config.logging import setup_logging
from app.parser.transaction_normalizer import TransactionNormalizer
from app.schemas.helius import WebhookTransaction
from app.schemas.trade import NormalizedTrade

# Import fixtures
from tests.fixtures.jupiter.swaps import JUPITER_FIXTURES
from tests.fixtures.raydium.swaps import RAYDIUM_FIXTURES
from tests.fixtures.pumpfun.swaps import PUMPFUN_FIXTURES
from tests.fixtures.edge_cases.swaps import EDGE_CASE_FIXTURES

# Import validation
from tests.validation.trade_validator import TradeValidator, ValidationResult

# Import snapshot manager
from tests.snapshots.manager import SnapshotManager, SnapshotComparator

logger = structlog.get_logger("corpus_runner")


class CorpusRunner:
    """Runs the complete parser test corpus."""

    def __init__(
        self,
        update_snapshots: bool = False,
        verbose: bool = False,
        protocol_filter: str | None = None,
    ) -> None:
        self._normalizer = TransactionNormalizer()
        self._validator = TradeValidator()
        self._snapshot_mgr = SnapshotManager()
        self._comparator = SnapshotComparator(self._snapshot_mgr)
        self._update = update_snapshots
        self._verbose = verbose

        # Filter fixtures by protocol if specified
        self._fixtures = self._load_fixtures(protocol_filter)

    def _load_fixtures(self, protocol_filter: str | None) -> list[dict[str, Any]]:
        """Load all fixtures, optionally filtered by protocol."""
        all_fixtures = []

        # Jupiter fixtures
        if protocol_filter is None or protocol_filter == "jupiter":
            for f in JUPITER_FIXTURES:
                f["protocol"] = "jupiter"
                all_fixtures.append(f)

        # Raydium fixtures
        if protocol_filter is None or protocol_filter == "raydium":
            for f in RAYDIUM_FIXTURES:
                f["protocol"] = "raydium"
                all_fixtures.append(f)

        # Pump.fun fixtures
        if protocol_filter is None or protocol_filter == "pumpfun":
            for f in PUMPFUN_FIXTURES:
                f["protocol"] = "pump.fun"
                all_fixtures.append(f)

        # Edge cases
        if protocol_filter is None:
            for f in EDGE_CASE_FIXTURES:
                f["protocol"] = "edge_case"
                all_fixtures.append(f)

        return all_fixtures

    def run(self) -> CorpusResult:
        """Run all tests and return results."""
        result = CorpusResult(total=len(self._fixtures))

        print("\n" + "=" * 70)
        print("  PARSER TEST CORPUS")
        print("=" * 70)
        print(f"  Fixtures: {len(self._fixtures)}")
        print(f"  Update snapshots: {self._update}")
        print("=" * 70)

        for i, fixture in enumerate(self._fixtures, 1):
            fixture_result = self._run_fixture(fixture, i)
            result.add_result(fixture_result)

        # Print summary
        self._print_summary(result)

        return result

    def _run_fixture(self, fixture: dict[str, Any], index: int) -> FixtureResult:
        """Run a single fixture test."""
        fixture_id = fixture["id"]
        description = fixture["description"]
        expected = fixture.get("expected")
        expected_error = fixture.get("expected_error")

        print(f"\n  [{index:>2}/{len(self._fixtures)}] {fixture_id}")
        print(f"      {description}")

        # Build WebhookTransaction from input
        try:
            tx = WebhookTransaction(**fixture["input"])
        except Exception as e:
            print(f"      ERROR: Failed to build transaction: {e}")
            return FixtureResult(
                fixture_id=fixture_id,
                success=False,
                error=f"Build error: {e}",
            )

        # Parse
        start_time = time.time()
        parse_result = self._normalizer.normalize(tx)
        parse_time = time.time() - start_time

        # Validate
        validation = ValidationResult()

        if expected is None:
            # Expecting failure
            if parse_result.success:
                validation.add_error(f"Expected failure but got success")
            elif expected_error and parse_result.error_code != expected_error:
                validation.add_error(
                    f"Expected error {expected_error}, got {parse_result.error_code}"
                )
        else:
            # Expecting success
            if not parse_result.success:
                validation.add_error(f"Parse failed: {parse_result.error}")
            elif parse_result.trade:
                # Validate against expected values
                trade_validation = self._validator.validate(parse_result.trade, expected)
                validation.errors.extend(trade_validation.errors)
                validation.warnings.extend(trade_validation.warnings)

        # Snapshot comparison
        snapshot_diff = None
        if parse_result.trade:
            snapshot_id = fixture_id
            actual = self._trade_to_snapshot(parse_result.trade)
            snapshot_diff = self._comparator.compare(
                snapshot_id,
                actual,
                update=self._update,
            )

        # Print results
        status = "PASS" if validation.valid else "FAIL"
        print(f"      Status:   {status}")
        print(f"      Time:     {parse_time*1000:.1f}ms")

        if parse_result.trade:
            trade = parse_result.trade
            print(f"      Protocol: {trade.protocol.value}")
            print(f"      Direction: {trade.direction.value}")
            print(f"      Token In:  {trade.token_in.amount} {trade.token_in.mint[:12]}...")
            print(f"      Token Out: {trade.token_out.amount} {trade.token_out.mint[:12]}...")

        if validation.errors:
            print(f"      Errors:")
            for err in validation.errors:
                print(f"        - {err}")

        if validation.warnings and self._verbose:
            print(f"      Warnings:")
            for warn in validation.warnings:
                print(f"        - {warn}")

        if snapshot_diff and not snapshot_diff.match and not self._update:
            print(f"      Snapshot: DIFF")
            if self._verbose:
                print(snapshot_diff.report())
        elif snapshot_diff and snapshot_diff.is_new:
            print(f"      Snapshot: NEW")
        elif snapshot_diff and snapshot_diff.updated:
            print(f"      Snapshot: UPDATED")

        return FixtureResult(
            fixture_id=fixture_id,
            success=validation.valid,
            errors=validation.errors,
            warnings=validation.warnings,
            parse_time_ms=parse_time * 1000,
            snapshot_match=snapshot_diff.match if snapshot_diff else None,
        )

    def _trade_to_snapshot(self, trade: NormalizedTrade) -> dict[str, Any]:
        """Convert a NormalizedTrade to snapshot format."""
        return {
            "wallet": trade.wallet,
            "direction": trade.direction.value,
            "protocol": trade.protocol.value,
            "token_in": {
                "mint": trade.token_in.mint,
                "amount": str(trade.token_in.amount),
                "decimals": trade.token_in.decimals,
            },
            "token_out": {
                "mint": trade.token_out.mint,
                "amount": str(trade.token_out.amount),
                "decimals": trade.token_out.decimals,
            },
            "fee_sol": str(trade.fee_sol),
        }

    def _print_summary(self, result: CorpusResult) -> None:
        """Print test summary."""
        print("\n" + "=" * 70)
        print("  CORPUS SUMMARY")
        print("=" * 70)
        print(f"  Total:   {result.total}")
        print(f"  Passed:  {result.passed}")
        print(f"  Failed:  {result.failed}")
        print(f"  Avg time: {result.avg_time_ms:.1f}ms")
        print(f"  Snapshots: {result.snapshot_matches} match, {result.snapshot_diffs} diff")

        if result.failed > 0:
            print("\n  FAILED FIXTURES:")
            for r in result.results:
                if not r.success:
                    print(f"    - {r.fixture_id}: {r.errors[0] if r.errors else 'unknown'}")

        print("=" * 70)


class FixtureResult:
    """Result of a single fixture test."""

    def __init__(
        self,
        fixture_id: str,
        success: bool,
        error: str | None = None,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
        parse_time_ms: float = 0,
        snapshot_match: bool | None = None,
    ) -> None:
        self.fixture_id = fixture_id
        self.success = success
        self.error = error
        self.errors = errors or []
        self.warnings = warnings or []
        self.parse_time_ms = parse_time_ms
        self.snapshot_match = snapshot_match


class CorpusResult:
    """Aggregate result of all fixture tests."""

    def __init__(self, total: int) -> None:
        self.total = total
        self.results: list[FixtureResult] = []
        self.passed = 0
        self.failed = 0
        self.snapshot_matches = 0
        self.snapshot_diffs = 0
        self.total_time_ms = 0

    def add_result(self, result: FixtureResult) -> None:
        self.results.append(result)
        if result.success:
            self.passed += 1
        else:
            self.failed += 1
        if result.snapshot_match is True:
            self.snapshot_matches += 1
        elif result.snapshot_match is False:
            self.snapshot_diffs += 1
        self.total_time_ms += result.parse_time_ms

    @property
    def avg_time_ms(self) -> float:
        return self.total_time_ms / max(len(self.results), 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run parser test corpus")
    parser.add_argument(
        "--update-snapshots",
        action="store_true",
        help="Update snapshots with current output",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--protocol",
        choices=["jupiter", "raydium", "pumpfun"],
        help="Filter by protocol",
    )
    args = parser.parse_args()

    setup_logging(log_level="DEBUG" if args.verbose else "INFO", json_output=False)

    runner = CorpusRunner(
        update_snapshots=args.update_snapshots,
        verbose=args.verbose,
        protocol_filter=args.protocol,
    )

    result = runner.run()

    # Exit with error code if any tests failed
    sys.exit(1 if result.failed > 0 else 0)


if __name__ == "__main__":
    main()
