"""Broad cryptocurrency strategy.

Targets all crypto-related Polymarket markets EXCEPT Bitcoin-specific ones
(those are handled by BitcoinStrategy). Covers altcoins, DeFi protocols,
exchanges, stablecoins, regulation, and general crypto themes.

Toggle via CRYPTO_STRATEGY_ENABLED=true/false in .env.
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
from polybot.strategies.bitcoin import is_btc_market

logger = logging.getLogger(__name__)

# Patterns that identify crypto-related (non-BTC) markets
_CRYPTO_PATTERNS = [
    # Major coins / tokens
    re.compile(r"\b(ethereum|ETH)\b", re.IGNORECASE),
    re.compile(r"\b(solana|SOL)\b", re.IGNORECASE),
    re.compile(r"\b(cardano|ADA)\b", re.IGNORECASE),
    re.compile(r"\b(ripple|XRP)\b", re.IGNORECASE),
    re.compile(r"\b(dogecoin|DOGE)\b", re.IGNORECASE),
    re.compile(r"\b(polkadot|DOT)\b", re.IGNORECASE),
    re.compile(r"\b(avalanche|AVAX)\b", re.IGNORECASE),
    re.compile(r"\b(chainlink|LINK)\b", re.IGNORECASE),
    re.compile(r"\b(polygon|MATIC|POL)\b", re.IGNORECASE),
    re.compile(r"\b(litecoin|LTC)\b", re.IGNORECASE),
    re.compile(r"\b(uniswap|UNI)\b", re.IGNORECASE),
    re.compile(r"\b(aave|AAVE)\b", re.IGNORECASE),
    re.compile(r"\bmemecoin\b", re.IGNORECASE),
    re.compile(r"\bshitcoin\b", re.IGNORECASE),
    re.compile(r"\baltcoin\b", re.IGNORECASE),

    # Themes
    re.compile(r"\bcrypto\b", re.IGNORECASE),
    re.compile(r"\bcryptocurrenc", re.IGNORECASE),
    re.compile(r"\bdefi\b", re.IGNORECASE),
    re.compile(r"\bdecentralized\s+finance\b", re.IGNORECASE),
    re.compile(r"\bstablecoin\b", re.IGNORECASE),
    re.compile(r"\bUSDC\b"),
    re.compile(r"\bUSDT\b"),
    re.compile(r"\btether\b", re.IGNORECASE),
    re.compile(r"\btoken\s+launch\b", re.IGNORECASE),
    re.compile(r"\bFDV\b"),
    re.compile(r"\bmarket\s+cap\b", re.IGNORECASE),
    re.compile(r"\bNFT\b"),
    re.compile(r"\bweb3\b", re.IGNORECASE),
    re.compile(r"\bDAO\b"),
    re.compile(r"\bSEC\s+.*crypto\b", re.IGNORECASE),
    re.compile(r"\bcoinbase\b", re.IGNORECASE),
    re.compile(r"\bbinance\b", re.IGNORECASE),
    re.compile(r"\bkraken\b", re.IGNORECASE),
    re.compile(r"\bblockchain\b", re.IGNORECASE),
    re.compile(r"\bL1\b"),
    re.compile(r"\bL2\b"),
    re.compile(r"\brollup\b", re.IGNORECASE),
    re.compile(r"\bairdrop\b", re.IGNORECASE),
]


def is_crypto_market(market: Market) -> bool:
    """Return True if the market is crypto-related but NOT Bitcoin-specific."""
    if is_btc_market(market):
        return False
    for pat in _CRYPTO_PATTERNS:
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
class _CryptoMarketState:
    history: deque
    last_signal_side: str | None = None
    position_size: float = 0.0


class CryptoBroadStrategy(BaseStrategy):
    """Momentum strategy for non-Bitcoin crypto prediction markets.

    Covers altcoins, DeFi, exchanges, regulation, token launches, etc.
    Slightly more conservative than BitcoinStrategy (lower leverage,
    lower hedge ratio) because altcoin markets tend to be less liquid.
    """

    name = "crypto_broad"

    def __init__(self) -> None:
        self.lookback = settings.crypto_lookback
        self.ema_fast = settings.crypto_ema_fast
        self.ema_slow = settings.crypto_ema_slow
        self.momentum_threshold = settings.crypto_momentum_threshold
        self.hedge_ratio = settings.crypto_hedge_ratio
        self.base_size_usd = settings.crypto_base_size_usd
        self.max_leverage = settings.crypto_max_leverage
        self.max_exposure_usd = settings.crypto_max_exposure_usd

        self._states: dict[str, _CryptoMarketState] = defaultdict(
            lambda: _CryptoMarketState(history=deque(maxlen=self.lookback))
        )

    def on_tick(self, markets: list[Market], context: dict[str, Any]) -> list[Signal]:
        if not settings.crypto_strategy_enabled:
            return []

        signals: list[Signal] = []
        midpoints = context.get("midpoints", {})

        crypto_markets = [m for m in markets if is_crypto_market(m)]
        if not crypto_markets:
            return []

        for mkt in crypto_markets:
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
                                            reason="crypto_momentum", conviction=conviction, leverage=leverage))
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
                                                reason="crypto_hedge", hedging=state.last_signal_side))

        return signals

    def _signal(self, market: Market, side: Side, outcome: str, price: float,
                size: float, **meta: Any) -> Signal:
        return Signal(
            market=market, side=side, outcome=outcome, price=price, size=size,
            order_type=OrderType.LIMIT,
            metadata={"strategy": self.name, "strategy_exposure_cap": self.max_exposure_usd, **meta},
        )

    def on_fill(self, signal: Signal, fill_info: dict[str, Any]) -> None:
        logger.info("CRYPTO FILL [%s]: %s %s @ %.4f on '%s'",
                     signal.metadata.get("reason"), signal.side.value,
                     signal.outcome, signal.price, signal.market.question)

    def on_cancel(self, signal: Signal, reason: str) -> None:
        logger.debug("CRYPTO CANCEL [%s]: %s on '%s'", reason, signal.outcome, signal.market.question)
