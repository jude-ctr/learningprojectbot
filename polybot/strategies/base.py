"""Abstract base class every strategy must implement."""

from __future__ import annotations

import abc
from typing import Any

from polybot.models import Market, Signal


class BaseStrategy(abc.ABC):
    """Inherit from this to build a new strategy.

    Lifecycle:
        1. ``on_tick`` is called each loop iteration with fresh market data.
        2. Return a (possibly empty) list of Signals for the engine to execute.
        3. ``on_fill`` is called when an order is confirmed filled.
    """

    name: str = "unnamed"

    @abc.abstractmethod
    def on_tick(self, markets: list[Market], context: dict[str, Any]) -> list[Signal]:
        """Evaluate markets and return trade signals (or empty list)."""
        ...

    def on_fill(self, signal: Signal, fill_info: dict[str, Any]) -> None:
        """Optional hook called after a fill is confirmed."""

    def on_cancel(self, signal: Signal, reason: str) -> None:
        """Optional hook called when an order is cancelled (e.g. by risk)."""
