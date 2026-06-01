"""API Key Manager — automatic rotation when credits exhausted.

Security:
- Config file permissions checked on startup (warns if world-readable)
- No raw key values logged
- Audit trail for state changes
"""

from __future__ import annotations

import json
import os
import stat
import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

CONFIG_FILE = "/root/solana-wallet-intel/config/api_keys.json"


def _check_file_permissions() -> None:
    """Warn if api_keys.json is world-readable."""
    try:
        if not os.path.exists(CONFIG_FILE):
            return
        file_stat = os.stat(CONFIG_FILE)
        mode = file_stat.st_mode
        if mode & stat.S_IROTH:
            logger.warning(
                "api_keys.file_world_readable",
                path=CONFIG_FILE,
                suggestion="Run: chmod 600 config/api_keys.json",
            )
    except Exception:
        pass


class ApiKeyManager:
    """Manages multiple Helius API keys with automatic rotation."""

    def __init__(self) -> None:
        self._keys: list[dict[str, Any]] = []
        self._current_index: int = 0
        self._last_check: float = 0
        self._cooldown_until: float = 0
        _check_file_permissions()
        self._load_config()

    def _load_config(self) -> None:
        """Load API keys from config file."""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r") as f:
                    config = json.load(f)
                    self._keys = config.get("api_keys", [])
                    self._current_index = config.get("current_index", 0)
                logger.info("api_key.config_loaded", key_count=len(self._keys))
            else:
                primary_key = os.getenv("HELIUS_API_KEY", "")
                if primary_key:
                    self._keys = [{"key": primary_key, "name": "primary", "active": True}]
                logger.info("api_key.env_fallback", has_key=bool(primary_key))
        except Exception as e:
            logger.error("api_key.config_error", error=str(e))

    def _save_config(self) -> None:
        """Save current config to file with restricted permissions."""
        try:
            os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
            fd = os.open(CONFIG_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump({
                    "api_keys": self._keys,
                    "current_index": self._current_index,
                }, f, indent=2)
        except Exception as e:
            logger.error("api_key.save_error", error=str(e))

    def get_current_key(self) -> str:
        """Get current active API key."""
        if not self._keys:
            return os.getenv("HELIUS_API_KEY", "")

        if time.time() < self._cooldown_until:
            logger.debug("api_key.cooldown_active", retry_in=self._cooldown_until - time.time())
            return ""

        for i, key_info in enumerate(self._keys):
            if key_info.get("active", True):
                self._current_index = i
                return key_info["key"]

        logger.warning("api_key.all_exhausted")
        return ""

    def mark_exhausted(self, cooldown_seconds: int = 3600) -> None:
        """Mark current key as exhausted and rotate to next."""
        if self._keys and self._current_index < len(self._keys):
            self._keys[self._current_index]["active"] = False
            self._keys[self._current_index]["exhausted_at"] = time.time()
            logger.warning(
                "api_key.exhausted",
                key_name=self._keys[self._current_index].get("name", "unknown"),
                cooldown=cooldown_seconds,
            )

        self._current_index += 1
        for i in range(self._current_index, len(self._keys)):
            if self._keys[i].get("active", True):
                self._current_index = i
                logger.info(
                    "api_key.rotated",
                    new_key_name=self._keys[i].get("name", "unknown"),
                )
                self._save_config()
                return

        self._cooldown_until = time.time() + cooldown_seconds
        logger.warning("api_key.all_keys_exhausted", retry_in=cooldown_seconds)
        self._save_config()

    def mark_working(self) -> None:
        """Mark current key as working (reset cooldown)."""
        self._cooldown_until = 0
        if self._keys and self._current_index < len(self._keys):
            self._keys[self._current_index]["active"] = True
            self._keys[self._current_index]["last_used"] = time.time()

    def add_key(self, key: str, name: str = "") -> None:
        """Add a new API key."""
        self._keys.append({
            "key": key,
            "name": name or f"key_{len(self._keys) + 1}",
            "active": True,
            "added_at": time.time(),
        })
        self._save_config()
        logger.info("api_key.added", name=name, total=len(self._keys))

    def remove_key(self, index: int) -> None:
        """Remove an API key by index."""
        if 0 <= index < len(self._keys):
            removed = self._keys.pop(index)
            if self._current_index >= len(self._keys):
                self._current_index = max(0, len(self._keys) - 1)
            self._save_config()
            logger.info("api_key.removed", name=removed.get("name", "unknown"))

    def get_status(self) -> dict[str, Any]:
        """Get current status of all keys (raw — used internally)."""
        return {
            "total_keys": len(self._keys),
            "current_index": self._current_index,
            "current_key_name": self._keys[self._current_index].get("name", "unknown") if self._keys else "none",
            "active_keys": sum(1 for k in self._keys if k.get("active", True)),
            "cooldown_remaining": max(0, self._cooldown_until - time.time()),
            "keys": [
                {
                    "name": k.get("name", "unknown"),
                    "active": k.get("active", True),
                    "exhausted_at": k.get("exhausted_at"),
                }
                for k in self._keys
            ],
        }


_manager: ApiKeyManager | None = None


def get_api_key_manager() -> ApiKeyManager:
    """Get or create the API key manager singleton."""
    global _manager
    if _manager is None:
        _manager = ApiKeyManager()
    return _manager
