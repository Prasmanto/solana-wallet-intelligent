"""Unrealized PnL engine — calculates mark-to-market PnL for positions.

Responsibilities:
- Calculate unrealized PnL for positions
- Compute wallet total valuation
- Detect illiquid tokens
- Provide ranking metrics

Design:
- Uses cached prices for performance
- Graceful degradation for missing prices
- Deterministic calculations
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import structlog

from app.analytics.pricing_service import PricingService
from app.infrastructure.database.models.wallet_position import WalletPosition
from app.schemas.pricing import (
    PositionValuation,
    PricingResult,
    TokenPrice,
    WalletValuation,
)
from app.schemas.position import PositionState

logger = structlog.get_logger(__name__)

# Illiquid token heuristics
ILLIQUID_THRESHOLD_CONFIDENCE = Decimal("0.5")
ILLIQUID_MIN_TRADES = 10


class UnrealizedPnLEngine:
    """Calculates unrealized PnL and wallet valuations."""

    def __init__(self, pricing_service: PricingService) -> None:
        self._pricing = pricing_service

    async def value_position(
        self,
        position: WalletPosition,
    ) -> PositionValuation | None:
        """Calculate valuation for a single position.

        Returns None if price is unavailable.
        """
        # Get current price
        price_data = await self._pricing.get_price(position.token_mint)
        if not price_data:
            return None

        position_size = Decimal(str(position.position_size))
        avg_cost = Decimal(str(position.avg_cost_basis))
        total_cost = Decimal(str(position.total_cost_basis))

        # Calculate market value
        market_value = position_size * price_data.price

        # Calculate unrealized PnL
        unrealized_pnl = market_value - total_cost
        unrealized_roi = (unrealized_pnl / total_cost * 100) if total_cost > 0 else Decimal("0")

        # Combined PnL
        realized_pnl = Decimal(str(position.realized_pnl))
        total_pnl = realized_pnl + unrealized_pnl
        total_roi = (total_pnl / total_cost * 100) if total_cost > 0 else Decimal("0")

        # Liquidity assessment
        confidence = await self._pricing.get_price_confidence(position.token_mint)
        is_illiquid = self._detect_illiquid(position, price_data)

        return PositionValuation(
            wallet=position.wallet,
            token_mint=position.token_mint,
            position_size=position_size,
            avg_cost_basis=avg_cost,
            total_cost_basis=total_cost,
            current_price=price_data.price,
            market_value=market_value,
            price_age_seconds=price_data.price_age_seconds,
            price_confidence=price_data.confidence,
            unrealized_pnl=unrealized_pnl,
            unrealized_roi=unrealized_roi,
            realized_pnl=realized_pnl,
            total_pnl=total_pnl,
            total_roi=total_roi,
            liquidity_confidence=confidence,
            is_illiquid=is_illiquid,
        )

    async def value_wallet(
        self,
        positions: list[WalletPosition],
    ) -> WalletValuation:
        """Calculate total valuation for a wallet."""
        valuations: list[PositionValuation] = []
        total_market = Decimal("0")
        total_cost = Decimal("0")
        total_unrealized = Decimal("0")
        total_realized = Decimal("0")
        illiquid_count = 0

        for position in positions:
            if position.position_size <= 0:
                continue

            valuation = await self.value_position(position)
            if valuation:
                valuations.append(valuation)
                total_market += valuation.market_value
                total_cost += valuation.total_cost_basis
                total_unrealized += valuation.unrealized_pnl
                total_realized += valuation.realized_pnl
                if valuation.is_illiquid:
                    illiquid_count += 1

        total_pnl = total_realized + total_unrealized
        total_roi = (total_pnl / total_cost * 100) if total_cost > 0 else Decimal("0")

        # Calculate liquidity score (0.0 to 1.0)
        if valuations:
            liquidity_score = Decimal(str(1 - (illiquid_count / len(valuations))))
        else:
            liquidity_score = Decimal("1.0")

        return WalletValuation(
            wallet=positions[0].wallet if positions else "",
            positions=valuations,
            total_market_value=total_market,
            total_cost_basis=total_cost,
            total_unrealized_pnl=total_unrealized,
            total_realized_pnl=total_realized,
            total_pnl=total_pnl,
            total_roi=total_roi,
            liquidity_score=liquidity_score,
            illiquid_positions=illiquid_count,
            valued_at=datetime.now(timezone.utc),
            prices_fresh=all(
                v.price_age_seconds < 300 for v in valuations
            ) if valuations else False,
        )

    def _detect_illiquid(
        self,
        position: WalletPosition,
        price: TokenPrice,
    ) -> bool:
        """Detect if a token is likely illiquid.

        Heuristics:
        - Very low price confidence
        - Small position size relative to price
        - Price age is very old
        """
        # Low confidence suggests illiquid
        if price.confidence < ILLIQUID_THRESHOLD_CONFIDENCE:
            return True

        # Very old price suggests no recent trades
        if price.price_age_seconds > 3600:  # 1 hour
            return True

        # Zero price but non-zero position
        if price.price <= 0 and position.position_size > 0:
            return True

        return False


from datetime import datetime
