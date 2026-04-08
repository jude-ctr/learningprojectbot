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
    wallet_balance: float | None = None
    _strategy_exposure: dict[str, float] = field(default_factory=dict)
    _rejected: list[str] = field(default_factory=list)

    def update_balance(self, balance: float | None) -> None:
        """Update the known wallet balance (called by the engine)."""
        if balance is not None:
            self.wallet_balance = balance

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

        # Wallet balance check — block if order would exceed available funds
        if self.wallet_balance is not None:
            remaining = self.wallet_balance - self.total_exposure_usd
            if signal.size > remaining:
                self._reject(signal, f"insufficient balance: need ${signal.size:.2f} "
                             f"but only ${remaining:.2f} available "
                             f"(wallet ${self.wallet_balance:.2f} - exposure ${self.total_exposure_usd:.2f})")
                return False

        # Per-strategy exposure cap
        strategy_name = signal.metadata.get("strategy")
        cap = signal.metadata.get("strategy_exposure_cap")
        if strategy_name and cap is not None:
            current = self._strategy_exposure.get(strategy_name, 0.0)
            if current + signal.size > cap:
                self._reject(signal, f"strategy '{strategy_name}' exposure "
                             f"{current + signal.size:.2f} > cap {cap:.2f}")
                return False

        return True

    def record_order(self, signal: Signal) -> None:
        self.open_order_count += 1
        self.total_exposure_usd += signal.size
        strategy_name = signal.metadata.get("strategy")
        if strategy_name:
            self._strategy_exposure[strategy_name] = (
                self._strategy_exposure.get(strategy_name, 0.0) + signal.size
            )

    def record_cancel(self, strategy_name: str | None = None, size: float = 0.0) -> None:
        self.open_order_count = max(0, self.open_order_count - 1)
        self.total_exposure_usd = max(0.0, self.total_exposure_usd - size)
        if strategy_name and strategy_name in self._strategy_exposure:
            self._strategy_exposure[strategy_name] = max(
                0.0, self._strategy_exposure[strategy_name] - size
            )

    def get_strategy_exposure(self, strategy_name: str) -> float:
        return self._strategy_exposure.get(strategy_name, 0.0)

    def _reject(self, signal: Signal, reason: str) -> None:
        logger.warning("RISK REJECTED [%s]: %s – %s %s @ %.4f",
                       reason, signal.market.question, signal.side.value, signal.outcome, signal.price)
        self._rejected.append(reason)
