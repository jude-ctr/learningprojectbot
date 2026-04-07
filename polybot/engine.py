"""Core engine – the main loop that ties everything together.

    Connector (market data + execution)
         │
         ▼
    Strategy.on_tick()  →  [Signal, ...]
         │
         ▼
    RiskManager.check()
         │
         ▼
    Connector.place_order()
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from polybot.config import settings
from polybot.connectors.clob import PolymarketConnector
from polybot.models import Market
from polybot.risk.manager import RiskManager
from polybot.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class Engine:
    """Orchestrates the strategy → risk → execution pipeline."""

    def __init__(
        self,
        connector: PolymarketConnector,
        strategies: list[BaseStrategy],
        risk_manager: RiskManager | None = None,
    ) -> None:
        self.connector = connector
        self.strategies = strategies
        self.risk = risk_manager or RiskManager()
        self._running = False

    # ── Main loop ────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Start the tick loop.  Ctrl-C to stop."""
        self._running = True
        logger.info("Engine started – %d strategy(ies), tick=%.1fs",
                     len(self.strategies), settings.tick_interval_seconds)

        while self._running:
            try:
                await self._tick()
            except Exception:
                logger.exception("Unhandled error in tick")
            await asyncio.sleep(settings.tick_interval_seconds)

    def stop(self) -> None:
        self._running = False
        logger.info("Engine stopping")

    # ── Single tick ──────────────────────────────────────────────────────

    async def _tick(self) -> None:
        markets = self._fetch_markets()
        context = self._build_context(markets)

        for strategy in self.strategies:
            signals = strategy.on_tick(markets, context)
            for signal in signals:
                if not self.risk.check(signal):
                    strategy.on_cancel(signal, "risk_rejected")
                    continue
                result = self.connector.place_order(signal)
                if result:
                    self.risk.record_order(signal)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _fetch_markets(self) -> list[Market]:
        """Pull raw market data and convert to domain objects."""
        raw = self.connector.get_markets()
        markets: list[Market] = []
        for m in raw:
            markets.append(Market(
                condition_id=m.get("condition_id", ""),
                question=m.get("question", ""),
                token_ids=self._extract_token_ids(m),
                active=m.get("active", True),
            ))
        return markets

    def _build_context(self, markets: list[Market]) -> dict[str, Any]:
        """Enrich tick context with midpoints, order book snapshots, etc."""
        midpoints: dict[str, float] = {}
        for mkt in markets:
            yes_id = mkt.token_ids.get("YES")
            if yes_id:
                try:
                    midpoints[mkt.condition_id] = self.connector.get_midpoint(yes_id)
                except Exception:
                    logger.debug("Could not fetch midpoint for %s", mkt.condition_id)
        return {"midpoints": midpoints}

    @staticmethod
    def _extract_token_ids(raw: dict[str, Any]) -> dict[str, str]:
        tokens: dict[str, str] = {}
        for tok in raw.get("tokens", []):
            outcome = tok.get("outcome", "").upper()
            token_id = tok.get("token_id", "")
            if outcome and token_id:
                tokens[outcome] = token_id
        return tokens
