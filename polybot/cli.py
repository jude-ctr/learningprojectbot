"""CLI entry-point for the bot."""

from __future__ import annotations

import asyncio
import logging

from polybot.config import settings
from polybot.connectors.clob import PolymarketConnector
from polybot.engine import Engine
from polybot.risk.manager import RiskManager
from polybot.strategies.example_spread import MidpointSpread
from polybot.strategies.market_timing import MarketTimingHedge
from polybot.utils.logging import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging()
    logger.info("Polybot v0.1.0 – dry_run=%s", settings.dry_run)

    connector = PolymarketConnector()
    risk_manager = RiskManager()

    # ── Register strategies here ─────────────────────────────────────
    strategies = [
        MidpointSpread(spread_bps=200, size_usd=5.0),
        # Market-timing hedge – disable via MARKET_TIMING_ENABLED=false in .env
        MarketTimingHedge(),
        # Add more strategies as you build them:
        # YourAlphaStrategy(...),
    ]

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
