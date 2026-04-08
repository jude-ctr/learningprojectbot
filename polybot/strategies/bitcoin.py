"""Bitcoin-focused strategy.

Filters for BTC-related Polymarket markets (price targets, ETF flows,
hash rate, halving, Satoshi, etc.) and trades them with momentum +
hedging logic tuned for Bitcoin's volatility profile.

Toggle via BTC_STRATEGY_ENABLED=true/false in .env.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from polybot.config import settings
from polybot.models import Market, OrderType, Side, Signal
from polybot.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

# Patterns that identify a Bitcoin-related market
_BTC_PATTERNS = [
    re.compile(r"\bbitcoin\b", re.IGNORECASE),
    re.compile(r"\bBTC\b"),
    re.compile(r"\bsatoshi\b", re.IGNORECASE),
    re.compile(r"\bbitcoin\s+etf\b", re.IGNORECASE),
    re.compile(r"\bbtc\s+price\b", re.IGNORECASE),
    re.compile(r"\bbtc\s+etf\b", re.IGNORECASE),
    re.compile(r"\bhash\s*rate\b", re.IGNORECASE),
    re.compile(r"\bhalving\b", re.IGNORECASE),
    re.compile(r"\blightning\s+network\b", re.IGNORECASE),
    re.compile(r"\bsats\b", re.IGNORECASE),
]


def is_btc_market(market: Market) -> bool:
    """Return True if the market question is about Bitcoin."""
    for pat in _BTC_PATTERNS:
        if pat.search(market.question):
            return True
    return False


def _ema(prices: list[float], span: int) -> list[float]:
    if not prices:
        return []
    alpha = 2.0 / (span + 1)
    result = [prices[0]]
    for p in prices[1:]:
        result.append(alpha * p + (1 - alpha) * result[-1])
    return result


@dataclass
class _BTCMarketState:
    history: deque
    last_signal_side: str | None = None
    position_size: float = 0.0


class BitcoinStrategy(BaseStrategy):
    """Momentum strategy exclusively for Bitcoin-related prediction markets.

    Behaviour:
        - Scans all markets each tick, only acts on BTC-related ones
        - Uses faster EMA crossover tuned for crypto volatility
        - Higher default hedge ratio (0.6) — BTC markets can reverse fast
        - Leverage scales with conviction like MarketTimingHedge
    """

    name = "bitcoin"

    def __init__(self) -> None:
        self.lookback = settings.btc_lookback
        self.ema_fast = settings.btc_ema_fast
        self.ema_slow = settings.btc_ema_slow
        self.momentum_threshold = settings.btc_momentum_threshold
        self.hedge_ratio = settings.btc_hedge_ratio
        self.base_size_usd = settings.btc_base_size_usd
        self.max_leverage = settings.btc_max_leverage
        self.max_exposure_usd = settings.btc_max_exposure_usd

        self._states: dict[str, _BTCMarketState] = defaultdict(
            lambda: _BTCMarketState(history=deque(maxlen=self.lookback))
        )

    def filter_markets(self, markets: list[Market]) -> list[Market]:
        if not settings.btc_strategy_enabled:
            return []
        return [m for m in markets if is_btc_market(m)]

    def on_tick(self, markets: list[Market], context: dict[str, Any]) -> list[Signal]:
        if not settings.btc_strategy_enabled:
            return []

        signals: list[Signal] = []
        midpoints = context.get("midpoints", {})

        btc_markets = [m for m in markets if is_btc_market(m)]
        if not btc_markets:
            return []

        for mkt in btc_markets:
            mid = midpoints.get(mkt.condition_id)
            if mid is None:
                continue

            state = self._states[mkt.condition_id]
            state.history.append(mid)

            if len(state.history) < self.ema_slow:
                continue

            prices = list(state.history)
            ema_f = _ema(prices, self.ema_fast)
            ema_s = _ema(prices, self.ema_slow)

            spread = ema_f[-1] - ema_s[-1]
            velocity = spread - (ema_f[-2] - ema_s[-2]) if len(ema_f) >= 2 else 0.0
            conviction = min(abs(spread) / self.momentum_threshold, 1.0)
            strong = abs(spread) >= self.momentum_threshold

            if strong:
                leverage = 1.0 + (self.max_leverage - 1.0) * conviction
                sized = round(self.base_size_usd * leverage, 2)
                going_up = spread > 0
                outcome = "YES" if going_up else "NO"
                price = mid + 0.01 if going_up else (1.0 - mid) + 0.01
                price = round(min(max(price, 0.01), 0.99), 4)

                signals.append(self._signal(mkt, Side.BUY, outcome, price, sized,
                                            reason="btc_momentum", conviction=conviction, leverage=leverage))
                state.last_signal_side = outcome
                state.position_size = sized

            elif state.last_signal_side and state.position_size > 0 and self.hedge_ratio > 0:
                should_hedge = (
                    (state.last_signal_side == "YES" and velocity < 0)
                    or (state.last_signal_side == "NO" and velocity > 0)
                )
                if should_hedge:
                    hedge_outcome = "NO" if state.last_signal_side == "YES" else "YES"
                    hedge_size = round(state.position_size * self.hedge_ratio, 2)
                    hedge_price = mid if hedge_outcome == "YES" else (1.0 - mid)
                    hedge_price = round(min(max(hedge_price, 0.01), 0.99), 4)

                    signals.append(self._signal(mkt, Side.BUY, hedge_outcome, hedge_price, hedge_size,
                                                reason="btc_hedge", hedging=state.last_signal_side))
                    logger.info("BTC HEDGE: %s on '%s' → buying %s @ %.4f x $%.2f",
                                state.last_signal_side, mkt.question, hedge_outcome, hedge_price, hedge_size)

        return signals

    def _signal(self, market: Market, side: Side, outcome: str, price: float,
                size: float, **meta: Any) -> Signal:
        return Signal(
            market=market, side=side, outcome=outcome, price=price, size=size,
            order_type=OrderType.LIMIT,
            metadata={"strategy": self.name, "strategy_exposure_cap": self.max_exposure_usd, **meta},
        )

    def on_fill(self, signal: Signal, fill_info: dict[str, Any]) -> None:
        logger.info("BTC FILL [%s]: %s %s @ %.4f on '%s'",
                     signal.metadata.get("reason"), signal.side.value,
                     signal.outcome, signal.price, signal.market.question)

    def on_cancel(self, signal: Signal, reason: str) -> None:
        logger.debug("BTC CANCEL [%s]: %s on '%s'", reason, signal.outcome, signal.market.question)
