"""CLI entry-point for the bot."""

from __future__ import annotations

import asyncio
import logging

from polybot.config import settings
from polybot.connectors.clob import PolymarketConnector
from polybot.engine import Engine
from polybot.risk.manager import RiskManager
from polybot.strategies.base import BaseStrategy
from polybot.strategies.bitcoin import BitcoinStrategy
from polybot.strategies.crypto_broad import CryptoBroadStrategy
from polybot.strategies.example_spread import MidpointSpread
from polybot.strategies.market_timing import MarketTimingHedge
from polybot.utils.logging import setup_logging

logger = logging.getLogger(__name__)


def _build_strategies() -> list[BaseStrategy]:
    """Instantiate all strategies.  Each checks its own enabled flag at runtime."""
    strategies: list[BaseStrategy] = [
        MidpointSpread(spread_bps=200, size_usd=5.0),
        MarketTimingHedge(),
        BitcoinStrategy(),
        CryptoBroadStrategy(),
    ]

    # Log which strategies are active
    flags = {
        "midpoint_spread": settings.spread_enabled,
        "market_timing_hedge": settings.market_timing_enabled,
        "bitcoin": settings.btc_strategy_enabled,
        "crypto_broad": settings.crypto_strategy_enabled,
    }
    enabled = [name for name, on in flags.items() if on]
    disabled = [name for name, on in flags.items() if not on]

    logger.info("Market scope: %s", settings.market_scope.upper())
    if settings.market_timing_enabled:
        logger.info("  Market-timing scope: %s", settings.market_timing_scope.upper())
    logger.info("Strategies ENABLED:  %s", ", ".join(enabled) or "(none)")
    if disabled:
        logger.info("Strategies DISABLED: %s", ", ".join(disabled))
    if settings.confluence_enabled:
        logger.info("Confluence mode ON – min %d strategies must agree (size boost %.1fx)",
                     settings.confluence_min_agree, settings.confluence_size_boost)
    else:
        logger.info("Confluence mode OFF – all signals pass independently")

    return strategies


def main() -> None:
    setup_logging()
    logger.info("Polybot v0.2.0 – dry_run=%s", settings.dry_run)

    connector = PolymarketConnector()
    risk_manager = RiskManager()
    strategies = _build_strategies()

    engine = Engine(
        connector=connector,
        strategies=strategies,
        risk_manager=risk_manager,
    )

    try:
        asyncio.run(engine.run())
    except KeyboardInterrupt:
        engine.stop()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
