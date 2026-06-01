"""Liquidity burst simulator — realistic pre-pump market microstructure.

Simulates 4 event regimes:
1. NORMAL MODE (baseline noise)
2. ACCUMULATION MODE (pre-pump)
3. LIQUIDITY BURST MODE (critical) - with wave activation
4. DISTRIBUTION / EXIT MODE

Each regime generates realistic market behavior for testing
the pump prediction engine.
"""

from __future__ import annotations

import random
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class LiquidityBurstSimulator:
    """Simulates realistic pre-pump market microstructure."""

    def __init__(self, seed: int | None = None) -> None:
        if seed is not None:
            random.seed(seed)

        # Token pools
        self._tokens = [f"TOKEN_{i}" for i in range(10)]
        self._whale_wallets = [f"WHALE_{i}" for i in range(5)]
        self._bot_wallets = [f"BOT_{i}" for i in range(10)]
        self._retail_wallets = [f"RETAIL_{i}" for i in range(20)]

        # State
        self._current_regime = "NORMAL"
        self._regime_start = time.time()
        self._event_count = 0
        self._active_clusters: dict[str, list[str]] = {}

        # Wave tracking
        self._wave_wallets: list[str] = []
        self._co_occurrence: dict[tuple[str, str], int] = defaultdict(int)

    def generate_events(
        self,
        regime: str,
        duration_seconds: int = 60,
        target_token: str | None = None,
        spread_timestamps: bool = True,
    ) -> list[dict[str, Any]]:
        """Generate events for a specific regime."""
        self._current_regime = regime
        self._regime_start = time.time()

        if target_token is None:
            target_token = random.choice(self._tokens)

        events = []

        if regime == "NORMAL":
            events = self._generate_normal(duration_seconds, target_token)
        elif regime == "ACCUMULATION":
            events = self._generate_accumulation(duration_seconds, target_token)
        elif regime == "BURST":
            events = self._generate_burst(duration_seconds, target_token)
        elif regime == "DISTRIBUTION":
            events = self._generate_distribution(duration_seconds, target_token)

        if spread_timestamps:
            events = self._spread_timestamps(events)

        logger.info(
            "simulator.events_generated",
            regime=regime,
            token=target_token,
            event_count=len(events),
        )

        return events

    def generate_full_cycle(
        self,
        target_token: str | None = None,
    ) -> list[dict[str, Any]]:
        """Generate a full pump cycle."""
        if target_token is None:
            target_token = random.choice(self._tokens)

        events = []
        events.extend(self._generate_normal(10, target_token))
        events.extend(self._generate_accumulation(20, target_token))
        events.extend(self._generate_burst(15, target_token))
        events.extend(self._generate_distribution(15, target_token))

        logger.info(
            "simulator.full_cycle_complete",
            token=target_token,
            total_events=len(events),
        )

        return events

    # ── Regime Generators ───────────────────────────────────

    def _generate_normal(self, duration_seconds: int, token: str) -> list[dict[str, Any]]:
        """Normal market activity (baseline noise)."""
        events = []
        now = datetime.now(timezone.utc)
        event_count = random.randint(5, 20) * (duration_seconds // 60 + 1)

        for i in range(event_count):
            offset = random.uniform(0, duration_seconds)
            ts = now - timedelta(seconds=offset)
            wallet = random.choice(self._retail_wallets)
            event_type = random.choice(["BUY", "SELL", "TRANSFER"])
            amount = random.uniform(10, 100)
            token_addr = random.choice(self._tokens)

            events.append(self._create_event(
                wallet=wallet, event_type=event_type, amount=amount,
                token=token_addr, timestamp=ts, regime="NORMAL",
            ))

        return events

    def _generate_accumulation(self, duration_seconds: int, token: str) -> list[dict[str, Any]]:
        """Accumulation mode (pre-pump behavior)."""
        events = []
        now = datetime.now(timezone.utc)
        event_count = random.randint(20, 50) * (duration_seconds // 60 + 1)

        active_wallets = self._whale_wallets[:3] + self._bot_wallets[:5]

        for i in range(event_count):
            offset = random.uniform(0, duration_seconds)
            ts = now - timedelta(seconds=offset)
            time_ratio = offset / duration_seconds
            base_volume = random.uniform(100, 500)
            volume = base_volume * (1 + time_ratio * 0.5)
            wallet = random.choice(active_wallets)
            event_type = random.choices(["BUY", "SELL", "TRANSFER"], weights=[0.7, 0.2, 0.1])[0]

            events.append(self._create_event(
                wallet=wallet, event_type=event_type, amount=volume,
                token=token, timestamp=ts, regime="ACCUMULATION",
            ))

        return events

    def _generate_burst(self, duration_seconds: int, token: str) -> list[dict[str, Any]]:
        """Burst mode with wave activation and cluster feedback."""
        events = []
        now = datetime.now(timezone.utc)

        # CRITICAL: Compress wallet pool for high overlap
        # wallet_pool_size = max(5, int(wallet_pool_size * 0.5))
        burst_wallets = self._whale_wallets[:3] + self._bot_wallets[:3]  # Only 6 wallets!
        self._active_clusters["burst"] = burst_wallets

        # Wave activation model: 3 waves, each reuses previous wallets
        waves = []
        wave_wallets_used: list[str] = []

        for wave_num in range(3):
            # Each wave reuses wallets from previous wave
            if wave_num == 0:
                wave_wallets = random.sample(burst_wallets, min(4, len(burst_wallets)))
            else:
                # Reuse 70% of wallets from previous wave
                reuse_count = max(2, int(len(wave_wallets_used) * 0.7))
                wave_wallets = random.sample(
                    wave_wallets_used + burst_wallets,
                    min(reuse_count + 2, len(burst_wallets))
                )

            wave_wallets_used.extend(wave_wallets)
            waves.append(wave_wallets)

        # Generate events for each wave
        wave_duration = duration_seconds // 3

        for wave_num, wave_wallets in enumerate(waves):
            wave_start = now - timedelta(seconds=wave_num * wave_duration)
            wave_events = self._generate_wave(
                wave_wallets, wave_start, wave_duration, token, wave_num
            )
            events.extend(wave_events)

        self._active_clusters["burst"] = list(set(wave_wallets_used))

        logger.info(
            "simulator.burst_generated",
            token=token,
            event_count=len(events),
            wallet_count=len(set(wave_wallets_used)),
            waves=3,
        )

        return events

    def _generate_wave(
        self,
        wallets: list[str],
        wave_start: datetime,
        duration_seconds: int,
        token: str,
        wave_num: int,
    ) -> list[dict[str, Any]]:
        """Generate events for a single wave."""
        events = []

        # Wave intensity increases with wave number
        intensity = 1.0 + (wave_num * 0.3)
        event_count = int(random.randint(30, 60) * intensity)

        # Volume spike: 3x-10x baseline, increasing with wave
        base_volume = random.uniform(500, 1500)
        volume_multiplier = random.uniform(3, 8) * intensity

        for i in range(event_count):
            # Compressed time window: 30-45 seconds per wave
            offset = random.uniform(0, min(duration_seconds, 45))
            ts = wave_start - timedelta(seconds=offset)

            # Wallet reuse probability: 0.7
            if random.random() < 0.7 and len(waves_used := wallets) > 1:
                wallet = random.choice(waves_used)
            else:
                wallet = random.choice(wallets)

            # Track co-occurrence
            for other_wallet in wallets:
                if other_wallet != wallet:
                    pair = tuple(sorted([wallet, other_wallet]))
                    self._co_occurrence[pair] += 1

            # BUY dominance during burst
            event_type = random.choices(["BUY", "SELL"], weights=[0.8, 0.2])[0]

            # Volume spike
            amount = base_volume * random.uniform(1, volume_multiplier)

            events.append(self._create_event(
                wallet=wallet, event_type=event_type, amount=amount,
                token=token, timestamp=ts, regime="BURST",
            ))

            # Correlated wallet activity (wave pattern)
            if random.random() < 0.5:  # 50% chance of correlated activity
                correlated_wallet = random.choice(wallets)
                if correlated_wallet != wallet:
                    corr_offset = random.uniform(0.1, 0.5)  # Tighter correlation
                    corr_ts = ts + timedelta(seconds=corr_offset)
                    corr_amount = amount * random.uniform(0.5, 1.5)

                    events.append(self._create_event(
                        wallet=correlated_wallet, event_type=event_type,
                        amount=corr_amount, token=token, timestamp=corr_ts,
                        regime="BURST",
                    ))

                    # Track co-occurrence for cluster boost
                    pair = tuple(sorted([wallet, correlated_wallet]))
                    self._co_occurrence[pair] += 1

        return events

    def _generate_distribution(self, duration_seconds: int, token: str) -> list[dict[str, Any]]:
        """Distribution/exit mode."""
        events = []
        now = datetime.now(timezone.utc)
        event_count = random.randint(15, 40) * (duration_seconds // 60 + 1)
        distribution_wallets = self._retail_wallets[:10] + self._bot_wallets[:5]

        for i in range(event_count):
            offset = random.uniform(0, duration_seconds)
            ts = now - timedelta(seconds=offset)
            time_ratio = offset / duration_seconds
            base_volume = random.uniform(200, 800)
            volume = base_volume * (1 - time_ratio * 0.3)
            wallet = random.choice(distribution_wallets)
            event_type = random.choices(["BUY", "SELL"], weights=[0.2, 0.8])[0]

            events.append(self._create_event(
                wallet=wallet, event_type=event_type, amount=volume,
                token=token, timestamp=ts, regime="DISTRIBUTION",
            ))

        return events

    # ── Event Creation ──────────────────────────────────────

    def _create_event(
        self,
        wallet: str,
        event_type: str,
        amount: float,
        token: str,
        timestamp: datetime,
        regime: str,
    ) -> dict[str, Any]:
        """Create a single event."""
        self._event_count += 1

        if event_type == "BUY":
            token_in = SOL_MINT
            token_out = token
        elif event_type == "SELL":
            token_in = token
            token_out = SOL_MINT
        else:
            token_in = token
            token_out = SOL_MINT

        return {
            "signature": f"SIM_{self._event_count:06d}_{int(timestamp.timestamp())}",
            "wallet": wallet,
            "token_in": token_in,
            "token_out": token_out,
            "amount": amount,
            "timestamp": timestamp.timestamp(),
            "event_type": event_type,
            "token": token,
            "regime": regime,
            "slot": int(timestamp.timestamp() * 1000),
        }

    def get_active_clusters(self) -> dict[str, list[str]]:
        """Get currently active wallet clusters."""
        return dict(self._active_clusters)

    def get_co_occurrence(self) -> dict[tuple[str, str], int]:
        """Get co-occurrence frequencies."""
        return dict(self._co_occurrence)

    def _spread_timestamps(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Spread event timestamps to avoid cooldown issues."""
        if len(events) <= 1:
            return events
        events.sort(key=lambda e: e.get("timestamp", 0))
        min_spacing = 1.0
        last_ts = events[0].get("timestamp", 0)
        for event in events[1:]:
            current_ts = event.get("timestamp", 0)
            if current_ts - last_ts < min_spacing:
                event["timestamp"] = last_ts + min_spacing
            last_ts = event.get("timestamp", 0)
        return events


SOL_MINT = "So11111111111111111111111111111111111111112"
