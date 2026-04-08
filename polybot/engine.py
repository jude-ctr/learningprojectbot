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
import traceback
from typing import Any

from polybot.config import settings
from polybot.connectors.clob import PolymarketConnector
from polybot.models import Market
from polybot.risk.manager import RiskManager
from polybot.strategies.base import BaseStrategy
from polybot.strategies.confluence import ConfluenceFilter
from polybot.utils.market_filter import filter_by_scope

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_ERRORS = 5


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
        self._cached_markets: list[Market] = []
        self._market_refresh_counter = 0
        self._market_refresh_interval = 30  # refresh market list every N ticks
        self._balance_refresh_interval = 10  # refresh balance every N ticks
        self._balance_refresh_counter = 0

    # ── Main loop ────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Start the tick loop.  Ctrl-C to stop."""
        self._running = True
        consecutive_errors = 0

        logger.info("Engine started – %d strategy(ies), tick=%.1fs",
                     len(self.strategies), settings.tick_interval_seconds)

        while self._running:
            try:
                await self._tick()
                consecutive_errors = 0
            except Exception as exc:
                consecutive_errors += 1
                tb = traceback.format_exc()
                logger.error(
                    "Tick error (%d/%d consecutive):\n%s",
                    consecutive_errors, MAX_CONSECUTIVE_ERRORS, tb,
                )
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.critical(
                        "Hit %d consecutive tick errors – shutting down. "
                        "Last error: %s: %s",
                        MAX_CONSECUTIVE_ERRORS, type(exc).__name__, exc,
                    )
                    self._running = False
                    raise
            await asyncio.sleep(settings.tick_interval_seconds)

    def stop(self) -> None:
        self._running = False
        logger.info("Engine stopping")

    def shutdown(self) -> None:
        """Graceful shutdown: cancel all open orders on Polymarket."""
        self.stop()
        if not settings.cancel_on_shutdown:
            logger.info("CANCEL_ON_SHUTDOWN=false – leaving orders open")
            return
        if settings.dry_run:
            logger.info("Dry-run mode – no live orders to cancel")
            return
        logger.info("Cancelling all open orders on Polymarket...")
        try:
            open_orders = self.connector.get_open_orders()
            if not open_orders:
                logger.info("No open orders found")
                return
            logger.info("Found %d open order(s) – cancelling...", len(open_orders))
            result = self.connector.cancel_all()
            logger.info("Cancel-all result: %s", result)
        except Exception:
            logger.exception("Failed to cancel orders during shutdown")

    # ── Single tick ──────────────────────────────────────────────────────

    async def _tick(self) -> None:
        # Refresh market list periodically (not every tick)
        if not self._cached_markets or self._market_refresh_counter >= self._market_refresh_interval:
            self._cached_markets = self._fetch_markets()
            self._market_refresh_counter = 0

        self._market_refresh_counter += 1

        # Refresh wallet balance periodically
        if self._balance_refresh_counter >= self._balance_refresh_interval or self.risk.wallet_balance is None:
            balance = self.connector.get_usdc_balance()
            if balance is not None:
                self.risk.update_balance(balance)
                logger.info("Wallet USDC balance: $%.2f", balance)
            self._balance_refresh_counter = 0
        self._balance_refresh_counter += 1

        # Apply global market scope filter
        markets = filter_by_scope(self._cached_markets, settings.market_scope)

        if not markets:
            logger.warning("No tradeable markets in scope '%s' – skipping tick", settings.market_scope)
            return

        # Pre-filter: only fetch prices for markets that at least one
        # enabled strategy actually needs.  This avoids 40+ API calls
        # when only a niche strategy (e.g. BTC-only) is enabled.
        needed_ids: set[str] = set()
        for strategy in self.strategies:
            for m in strategy.filter_markets(markets):
                needed_ids.add(m.condition_id)

        price_markets = [m for m in markets if m.condition_id in needed_ids] if needed_ids else markets
        logger.info("Strategies need prices for %d / %d scoped markets", len(price_markets), len(markets))

        context = self._build_context(price_markets)

        # Pass wallet balance so strategies can compute %-based sizing
        context["wallet_balance"] = self.risk.wallet_balance

        if not context.get("midpoints"):
            logger.warning("No midpoints available – skipping tick")
            return

        # Collect signals from all strategies
        confluence = ConfluenceFilter()
        strategy_signals: dict[str, list] = {}
        for strategy in self.strategies:
            signals = strategy.on_tick(markets, context)
            strategy_signals[strategy.name] = signals
            confluence.add_signals(strategy.name, signals)

        # Apply confluence filter (pass-through if disabled)
        final_signals = confluence.resolve()
        confluence.reset()

        # Execute signals through risk gate
        for signal in final_signals:
            if not self.risk.check(signal):
                # Notify the originating strategy
                strat_name = signal.metadata.get("strategy", "")
                for strategy in self.strategies:
                    if strategy.name == strat_name:
                        strategy.on_cancel(signal, "risk_rejected")
                        break
                continue
            result = self.connector.place_order(signal)
            if result:
                self.risk.record_order(signal)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _fetch_markets(self) -> list[Market]:
        """Pull raw market data and convert to domain objects.

        A market is tradeable when:
          - accepting_orders is truthy (the order book is open)
          - closed is falsy (not resolved)
          - has valid token IDs
        """
        raw = self.connector.get_markets()

        markets: list[Market] = []
        skipped = 0
        for m in raw:
            if not isinstance(m, dict):
                continue
            if not m.get("accepting_orders", False):
                skipped += 1
                continue
            if m.get("closed", False):
                skipped += 1
                continue

            token_ids = self._extract_token_ids(m)
            if not token_ids:
                skipped += 1
                continue

            markets.append(Market(
                condition_id=m.get("condition_id", ""),
                question=m.get("question", ""),
                token_ids=token_ids,
                active=True,
            ))
        logger.info("Loaded %d tradeable markets (skipped %d closed/inactive)", len(markets), skipped)
        return markets

    def _build_context(self, markets: list[Market]) -> dict[str, Any]:
        """Enrich tick context with midpoints via batch price fetch.

        Uses get_prices_batch for a single HTTP request instead of
        one request per market.  Falls back to get_last_trade_prices_batch,
        then individual midpoint calls.
        """
        # Collect all YES token IDs
        token_to_condition: dict[str, str] = {}
        for mkt in markets:
            yes_id = mkt.token_ids.get("YES")
            if yes_id:
                token_to_condition[yes_id] = mkt.condition_id

        if not token_to_condition:
            return {"midpoints": {}}

        token_ids = list(token_to_condition.keys())

        # Try batch price fetch first (single HTTP call)
        prices = self.connector.get_prices_batch(token_ids)

        # Fall back to last-trade prices for any missing
        missing = [tid for tid in token_ids if tid not in prices]
        if missing:
            last_trade = self.connector.get_last_trade_prices_batch(missing)
            prices.update(last_trade)

        # Last resort: individual midpoint calls for still-missing
        still_missing = [tid for tid in token_ids if tid not in prices]
        if still_missing:
            logger.info("Batch prices got %d/%d, trying %d individual midpoints",
                        len(prices), len(token_ids), min(len(still_missing), 20))
            for tid in still_missing[:20]:  # cap individual calls
                mid = self.connector.get_midpoint(tid)
                if mid is not None:
                    prices[tid] = mid

        # Map back to condition_ids
        midpoints: dict[str, float] = {}
        for tid, price in prices.items():
            cid = token_to_condition.get(tid)
            if cid:
                midpoints[cid] = price

        logger.info("Got prices for %d / %d markets", len(midpoints), len(markets))
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
