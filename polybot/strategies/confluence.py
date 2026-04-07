"""Confluence filter – combines signals from multiple strategies.

When CONFLUENCE_ENABLED=true, the engine routes all strategy signals
through this filter before execution. A signal only passes if at least
CONFLUENCE_MIN_AGREE strategies agree on the same market + direction.

When multiple strategies agree, the signal size gets boosted by
CONFLUENCE_SIZE_BOOST (e.g., 1.5x).

When CONFLUENCE_ENABLED=false, all signals pass through unmodified.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from polybot.config import settings
from polybot.models import Signal

logger = logging.getLogger(__name__)


class ConfluenceFilter:
    """Aggregates signals across strategies and filters by agreement.

    Usage in engine:
        cf = ConfluenceFilter()
        # Collect signals from each strategy
        for strategy in strategies:
            cf.add_signals(strategy.name, strategy.on_tick(markets, context))
        # Get only the signals that pass confluence
        final_signals = cf.resolve()
    """

    def __init__(self) -> None:
        self.min_agree = settings.confluence_min_agree
        self.size_boost = settings.confluence_size_boost
        # key = (condition_id, outcome, side) → list of (strategy_name, signal)
        self._buckets: dict[tuple[str, str, str], list[tuple[str, Signal]]] = defaultdict(list)
        self._all_signals: list[tuple[str, Signal]] = []

    def add_signals(self, strategy_name: str, signals: list[Signal]) -> None:
        """Register signals from one strategy."""
        for sig in signals:
            key = (sig.market.condition_id, sig.outcome, sig.side.value)
            self._buckets[key].append((strategy_name, sig))
            self._all_signals.append((strategy_name, sig))

    def resolve(self) -> list[Signal]:
        """Return signals that meet the confluence threshold.

        If confluence is disabled, returns all signals unmodified.
        """
        if not settings.confluence_enabled:
            return [sig for _, sig in self._all_signals]

        resolved: list[Signal] = []
        seen_keys: set[tuple[str, str, str]] = set()

        for key, entries in self._buckets.items():
            if key in seen_keys:
                continue
            seen_keys.add(key)

            strategy_names = {name for name, _ in entries}
            agreement_count = len(strategy_names)

            if agreement_count < self.min_agree:
                logger.debug("CONFLUENCE SKIP: %s – only %d strategy(ies) agree (%s)",
                             key, agreement_count, ", ".join(strategy_names))
                continue

            # Pick the best signal (highest size) and boost it
            best_signal = max(entries, key=lambda e: e[1].size)[1]
            boosted_size = round(best_signal.size * self.size_boost, 2)

            boosted = Signal(
                market=best_signal.market,
                side=best_signal.side,
                outcome=best_signal.outcome,
                price=best_signal.price,
                size=boosted_size,
                order_type=best_signal.order_type,
                metadata={
                    **best_signal.metadata,
                    "confluence": True,
                    "confluence_strategies": sorted(strategy_names),
                    "confluence_count": agreement_count,
                    "original_size": best_signal.size,
                },
            )
            resolved.append(boosted)
            logger.info("CONFLUENCE HIT: %d strategies agree on %s %s '%s' → size $%.2f (boosted from $%.2f)",
                        agreement_count, best_signal.side.value, best_signal.outcome,
                        best_signal.market.question[:60], boosted_size, best_signal.size)

        logger.info("Confluence: %d signals in → %d signals out (min_agree=%d)",
                     len(self._all_signals), len(resolved), self.min_agree)
        return resolved

    def reset(self) -> None:
        """Clear state for the next tick."""
        self._buckets.clear()
        self._all_signals.clear()
