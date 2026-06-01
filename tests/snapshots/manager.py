"""Snapshot testing framework for parser normalization.

Provides:
- Snapshot file management (load/save/update)
- Deterministic snapshot comparison
- Snapshot diff reporting
- Auto-update mode for CI/CD
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Snapshot storage directory
SNAPSHOTS_DIR = Path(__file__).parent.parent / "snapshots"


class SnapshotManager:
    """Manages golden test snapshots for parser normalization."""

    def __init__(self, snapshots_dir: Path | None = None) -> None:
        self._dir = snapshots_dir or SNAPSHOTS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def load(self, snapshot_id: str) -> dict[str, Any] | None:
        """Load a snapshot by ID."""
        path = self._get_path(snapshot_id)
        if not path.exists():
            return None

        with open(path, "r") as f:
            return json.load(f)

    def save(self, snapshot_id: str, data: dict[str, Any]) -> None:
        """Save a snapshot."""
        path = self._get_path(snapshot_id)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True, default=str)
        logger.debug("snapshot.saved", snapshot_id=snapshot_id, path=str(path))

    def exists(self, snapshot_id: str) -> bool:
        """Check if a snapshot exists."""
        return self._get_path(snapshot_id).exists()

    def list_all(self) -> list[str]:
        """List all snapshot IDs."""
        return [
            p.stem
            for p in self._dir.glob("*.json")
        ]

    def delete(self, snapshot_id: str) -> bool:
        """Delete a snapshot."""
        path = self._get_path(snapshot_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def _get_path(self, snapshot_id: str) -> Path:
        """Get the file path for a snapshot ID."""
        # Sanitize ID for filename
        safe_id = snapshot_id.replace("/", "_").replace("\\", "_")
        return self._dir / f"{safe_id}.json"


class SnapshotComparator:
    """Compares actual output against stored snapshots."""

    def __init__(self, manager: SnapshotManager | None = None) -> None:
        self._manager = manager or SnapshotManager()

    def compare(
        self,
        snapshot_id: str,
        actual: dict[str, Any],
        update: bool = False,
    ) -> SnapshotDiff:
        """Compare actual output against stored snapshot.

        Args:
            snapshot_id: The snapshot identifier
            actual: The actual output to compare
            update: If True, update the snapshot with actual value

        Returns:
            SnapshotDiff with comparison results
        """
        stored = self._manager.load(snapshot_id)

        if stored is None:
            if update:
                self._manager.save(snapshot_id, actual)
                return SnapshotDiff(
                    match=False,
                    is_new=True,
                    message=f"New snapshot created: {snapshot_id}",
                )
            return SnapshotDiff(
                match=False,
                is_new=True,
                message=f"Snapshot not found: {snapshot_id}",
            )

        # Compare
        differences = self._diff(stored, actual)

        if differences and update:
            self._manager.save(snapshot_id, actual)
            return SnapshotDiff(
                match=False,
                differences=differences,
                message=f"Snapshot updated: {snapshot_id}",
                updated=True,
            )

        return SnapshotDiff(
            match=len(differences) == 0,
            differences=differences,
            message="Match" if not differences else f"{len(differences)} differences found",
        )

    def _diff(
        self,
        expected: Any,
        actual: Any,
        path: str = "",
    ) -> list[dict[str, Any]]:
        """Recursively compare two values and return differences."""
        differences = []

        if type(expected) != type(actual):
            differences.append({
                "path": path or "$",
                "type": "type_mismatch",
                "expected": f"{type(expected).__name__}: {expected}",
                "actual": f"{type(actual).__name__}: {actual}",
            })
            return differences

        if isinstance(expected, dict):
            all_keys = set(expected.keys()) | set(actual.keys())
            for key in sorted(all_keys):
                sub_path = f"{path}.{key}" if path else key
                if key not in expected:
                    differences.append({
                        "path": sub_path,
                        "type": "missing_expected",
                        "expected": None,
                        "actual": actual[key],
                    })
                elif key not in actual:
                    differences.append({
                        "path": sub_path,
                        "type": "missing_actual",
                        "expected": expected[key],
                        "actual": None,
                    })
                else:
                    differences.extend(
                        self._diff(expected[key], actual[key], sub_path)
                    )
        elif isinstance(expected, list):
            if len(expected) != len(actual):
                differences.append({
                    "path": path or "$",
                    "type": "length_mismatch",
                    "expected": len(expected),
                    "actual": len(actual),
                })
            for i in range(min(len(expected), len(actual))):
                differences.extend(
                    self._diff(expected[i], actual[i], f"{path}[{i}]")
                )
        elif expected != actual:
            differences.append({
                "path": path or "$",
                "type": "value_mismatch",
                "expected": expected,
                "actual": actual,
            })

        return differences


class SnapshotDiff:
    """Result of snapshot comparison."""

    def __init__(
        self,
        match: bool,
        differences: list[dict[str, Any]] | None = None,
        message: str = "",
        is_new: bool = False,
        updated: bool = False,
    ) -> None:
        self.match = match
        self.differences = differences or []
        self.message = message
        self.is_new = is_new
        self.updated = updated

    def __bool__(self) -> bool:
        return self.match

    def report(self) -> str:
        """Generate human-readable diff report."""
        if self.match:
            return "SNAPSHOT MATCH"

        lines = ["SNAPSHOT DIFFERENCES:"]
        for diff in self.differences:
            lines.append(f"  [{diff['type']}] {diff['path']}")
            lines.append(f"    Expected: {diff.get('expected')}")
            lines.append(f"    Actual:   {diff.get('actual')}")
        return "\n".join(lines)
