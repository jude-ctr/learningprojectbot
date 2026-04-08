"""Market-timing hedge strategy.

Uses EMA crossover on rolling midpoint history to detect momentum.
When momentum is strong → go directional with leverage-scaled size.
When momentum is weak/reversing → hedge the position by buying the opposite outcome.

Fully toggleable via MARKET_TIMING_ENABLED and scalable via leverage + risk knobs.

Signals carry metadata so the RiskManager enforces per-strategy exposure caps.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from polybot.config import settings
from polybot.models import Market, OrderType, Side, Signal
from polybot.strategies.base import BaseStrategy
from polybot.utils.market_filter import filter_by_scope

logger = logging.getLogger(__name__)


def _ema(prices: list[float], span: int) -> list[float]:
    """Compute exponential moving average over a price series."""
    if not prices:
        return []
    alpha = 2.0 / (span + 1)
    result = [prices[0]]
    for p in prices[1:]:
        result.append(alpha * p + (1 - alpha) * result[-1])
    return result


@dataclass
class _MarketState:
    """Per-market rolling state maintained across ticks."""
    history: deque  # midpoint history
    last_signal_side: str | None = None  # track what we're currently exposed to
    position_size: float = 0.0


class MarketTimingHedge(BaseStrategy):
    """Momentum-based directional strategy with automatic hedging.

    Behaviour by regime:
        STRONG UP   → BUY YES, sized up by leverage
        STRONG DOWN → BUY NO,  sized up by leverage
        WEAK / FLAT → hedge existing exposure (buy opposite outcome)
        NO DATA YET → skip (wait for lookback to fill)
    """

    name = "market_timing_hedge"

    def __init__(
        self,
        *,
        lookback: int | None = None,
        ema_fast: int | None = None,
        ema_slow: int | None = None,
        momentum_threshold: float | None = None,
        hedge_ratio: float | None = None,
        base_size_usd: float | None = None,
        max_leverage: float | None = None,
        max_exposure_usd: float | None = None,
        max_positions: int | None = None,
    ) -> None:
        # All params fall back to config, so you can override per-instance or via .env
        self.lookback = lookback or settings.market_timing_lookback
        self.ema_fast = ema_fast or settings.market_timing_ema_fast
        self.ema_slow = ema_slow or settings.market_timing_ema_slow
        self.momentum_threshold = momentum_threshold if momentum_threshold is not None else settings.market_timing_momentum_threshold
        self.hedge_ratio = hedge_ratio if hedge_ratio is not None else settings.market_timing_hedge_ratio
        self.base_size_usd = base_size_usd or settings.market_timing_base_size_usd
        self.max_leverage = max_leverage or settings.market_timing_max_leverage
        self.max_exposure_usd = max_exposure_usd or settings.market_timing_max_exposure_usd
        self.max_positions = max_positions or settings.market_timing_max_positions

        self._states: dict[str, _MarketState] = defaultdict(
            lambda: _MarketState(history=deque(maxlen=self.lookback))
        )
        self._active_position_count = 0

    # ── Core tick logic ──────────────────────────────────────────────────

    def filter_markets(self, markets: list[Market]) -> list[Market]:
        if not settings.market_timing_enabled:
            return []
        return filter_by_scope(markets, settings.market_timing_scope)

    def _resolve_sizes(self, wallet_balance: float | None) -> tuple[float, float]:
        """Return (base_size, max_exposure) based on sizing mode."""
        if settings.trade_size_mode == "percent" and wallet_balance and wallet_balance > 0:
            base = round(wallet_balance * settings.market_timing_base_size_pct / 100, 2)
            cap = round(wallet_balance * settings.market_timing_max_exposure_pct / 100, 2)
            return base, cap
        return self.base_size_usd, self.max_exposure_usd

    def on_tick(self, markets: list[Market], context: dict[str, Any]) -> list[Signal]:
        if not settings.market_timing_enabled:
            return []

        # Apply per-strategy scope filter
        scoped_markets = filter_by_scope(markets, settings.market_timing_scope)
        if not scoped_markets:
            return []

        signals: list[Signal] = []
        midpoints = context.get("midpoints", {})
        self._tick_base_size, self._tick_max_exposure = self._resolve_sizes(context.get("wallet_balance"))

        for mkt in scoped_markets:
            mid = midpoints.get(mkt.condition_id)
            if mid is None:
                continue

            state = self._states[mkt.condition_id]
            state.history.append(mid)

            if len(state.history) < self.ema_slow:
                continue  # not enough data yet

            prices = list(state.history)
            ema_f = _ema(prices, self.ema_fast)
            ema_s = _ema(prices, self.ema_slow)

            spread = ema_f[-1] - ema_s[-1]  # positive = upward momentum
            velocity = spread - (ema_f[-2] - ema_s[-2]) if len(ema_f) >= 2 else 0.0
            conviction = min(abs(spread) / self.momentum_threshold, 1.0)  # 0..1

            new_signals = self._evaluate_regime(mkt, mid, spread, velocity, conviction, state)
            signals.extend(new_signals)

        return signals

    def _evaluate_regime(
        self,
        market: Market,
        mid: float,
        spread: float,
        velocity: float,
        conviction: float,
        state: _MarketState,
    ) -> list[Signal]:
        """Decide whether to go directional, hedge, or sit flat."""
        signals: list[Signal] = []
        strong = abs(spread) >= self.momentum_threshold

        if strong:
            # ── Directional entry with leverage scaling ──────────────
            base = getattr(self, "_tick_base_size", self.base_size_usd)
            leverage = 1.0 + (self.max_leverage - 1.0) * conviction
            sized = round(base * leverage, 2)
            going_up = spread > 0

            outcome = "YES" if going_up else "NO"
            price = mid + 0.01 if going_up else (1.0 - mid) + 0.01
            price = round(min(max(price, 0.01), 0.99), 4)

            if self._active_position_count < self.max_positions:
                signals.append(self._make_signal(
                    market, Side.BUY, outcome, price, sized,
                    reason="momentum_entry",
                    conviction=conviction,
                    leverage=leverage,
                ))
                state.last_signal_side = outcome
                state.position_size = sized

        elif state.last_signal_side is not None and state.position_size > 0:
            # ── Momentum fading → hedge ──────────────────────────────
            # Velocity turning against us OR spread collapsed
            should_hedge = (
                (state.last_signal_side == "YES" and velocity < 0)
                or (state.last_signal_side == "NO" and velocity > 0)
                or not strong
            )
            if should_hedge and self.hedge_ratio > 0:
                hedge_outcome = "NO" if state.last_signal_side == "YES" else "YES"
                hedge_size = round(state.position_size * self.hedge_ratio, 2)
                hedge_price = mid if hedge_outcome == "YES" else (1.0 - mid)
                hedge_price = round(min(max(hedge_price, 0.01), 0.99), 4)

                signals.append(self._make_signal(
                    market, Side.BUY, hedge_outcome, hedge_price, hedge_size,
                    reason="hedge",
                    hedging_against=state.last_signal_side,
                ))
                logger.info(
                    "HEDGE: %s exposure on '%s' – buying %s @ %.4f x $%.2f",
                    state.last_signal_side, market.question,
                    hedge_outcome, hedge_price, hedge_size,
                )

        return signals

    # ── Signal factory ───────────────────────────────────────────────────

    def _make_signal(
        self,
        market: Market,
        side: Side,
        outcome: str,
        price: float,
        size: float,
        **extra_meta: Any,
    ) -> Signal:
        cap = getattr(self, "_tick_max_exposure", self.max_exposure_usd)
        return Signal(
            market=market,
            side=side,
            outcome=outcome,
            price=price,
            size=size,
            order_type=OrderType.LIMIT,
            metadata={
                "strategy": self.name,
                "strategy_exposure_cap": cap,
                **extra_meta,
            },
        )

    # ── Lifecycle hooks ──────────────────────────────────────────────────

    def on_fill(self, signal: Signal, fill_info: dict[str, Any]) -> None:
        reason = signal.metadata.get("reason", "")
        if reason == "momentum_entry":
            self._active_position_count += 1
        logger.info("FILL [%s]: %s %s @ %.4f on '%s'",
                     reason, signal.side.value, signal.outcome,
                     signal.price, signal.market.question)

    def on_cancel(self, signal: Signal, reason: str) -> None:
        logger.debug("CANCELLED [%s]: %s on '%s'", reason, signal.outcome, signal.market.question)
