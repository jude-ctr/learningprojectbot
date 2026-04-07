"""Pre-trade risk checks.

Sits between strategy signals and order execution.
Add checks here as your risk framework evolves.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from polybot.config import settings
from polybot.models import Signal

logger = logging.getLogger(__name__)


@dataclass
class RiskManager:
    """Gate-keeps signals before they reach the connector."""

    open_order_count: int = 0
    total_exposure_usd: float = 0.0
    _rejected: list[str] = field(default_factory=list)

    def check(self, signal: Signal) -> bool:
        """Return True if the signal passes all risk checks."""
        if signal.size > settings.max_position_size_usd:
            self._reject(signal, f"size {signal.size} > max {settings.max_position_size_usd}")
            return False

        if self.open_order_count >= settings.max_open_orders:
            self._reject(signal, f"open orders {self.open_order_count} >= max {settings.max_open_orders}")
            return False

        if not (0 < signal.price < 1):
            self._reject(signal, f"price {signal.price} out of (0,1) range")
            return False

        return True

    def record_order(self, signal: Signal) -> None:
        self.open_order_count += 1
        self.total_exposure_usd += signal.size

    def record_cancel(self) -> None:
        self.open_order_count = max(0, self.open_order_count - 1)

    def _reject(self, signal: Signal, reason: str) -> None:
        logger.warning("RISK REJECTED [%s]: %s – %s %s @ %.4f",
                       reason, signal.market.question, signal.side.value, signal.outcome, signal.price)
        self._rejected.append(reason)
