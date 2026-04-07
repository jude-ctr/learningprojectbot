"""Example strategy: naive midpoint spread.

This is a *placeholder* to show how strategies plug in.
Replace with your actual alpha logic.
"""

from __future__ import annotations

import logging
from typing import Any

from polybot.config import settings
from polybot.models import Market, OrderType, Side, Signal
from polybot.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

SPREAD_BPS = 200  # 2 cents each side of mid


class MidpointSpread(BaseStrategy):
    """Posts symmetric limit orders around the midpoint.

    Toggle via SPREAD_ENABLED=true/false in .env.
    """

    name = "midpoint_spread"

    def __init__(self, spread_bps: int = SPREAD_BPS, size_usd: float = 5.0) -> None:
        self.spread = spread_bps / 10_000
        self.size_usd = size_usd

    def on_tick(self, markets: list[Market], context: dict[str, Any]) -> list[Signal]:
        if not settings.spread_enabled:
            return []

        signals: list[Signal] = []
        for mkt in markets:
            mid = context.get("midpoints", {}).get(mkt.condition_id)
            if mid is None:
                continue

            bid_price = round(mid - self.spread / 2, 4)
            ask_price = round(mid + self.spread / 2, 4)

            if 0 < bid_price < 1:
                signals.append(Signal(
                    market=mkt, side=Side.BUY, outcome="YES",
                    price=bid_price, size=self.size_usd,
                    order_type=OrderType.LIMIT,
                ))
            if 0 < ask_price < 1:
                signals.append(Signal(
                    market=mkt, side=Side.SELL, outcome="YES",
                    price=ask_price, size=self.size_usd,
                    order_type=OrderType.LIMIT,
                ))
        return signals
