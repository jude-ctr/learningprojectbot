"""Tests for the market-timing hedge strategy."""

from __future__ import annotations

import os

# Force test-safe config before any polybot imports
os.environ.setdefault("DRY_RUN", "true")
os.environ.setdefault("MARKET_TIMING_ENABLED", "true")

from polybot.models import Market, Side
from polybot.strategies.market_timing import MarketTimingHedge, _ema


def _make_market(cid: str = "cond1") -> Market:
    return Market(condition_id=cid, question="Test?", token_ids={"YES": "tok1", "NO": "tok2"})


def _tick(strategy: MarketTimingHedge, mkt: Market, mid: float) -> list:
    return strategy.on_tick([mkt], {"midpoints": {mkt.condition_id: mid}})


# ── EMA utility ──────────────────────────────────────────────────────────

def test_ema_single_value():
    assert _ema([1.0], 5) == [1.0]


def test_ema_converges():
    prices = [0.5] * 50
    result = _ema(prices, 10)
    assert abs(result[-1] - 0.5) < 1e-10


def test_ema_responds_to_trend():
    prices = [0.4 + i * 0.01 for i in range(20)]
    fast = _ema(prices, 5)
    slow = _ema(prices, 15)
    # Fast EMA should be above slow in an uptrend
    assert fast[-1] > slow[-1]


# ── Kill switch ──────────────────────────────────────────────────────────

def test_disabled_strategy_returns_no_signals(monkeypatch):
    monkeypatch.setattr("polybot.strategies.market_timing.settings.market_timing_enabled", False)
    strategy = MarketTimingHedge(lookback=5, ema_fast=2, ema_slow=4)
    mkt = _make_market()
    # Feed enough ticks
    for mid in [0.5, 0.52, 0.54, 0.56, 0.58]:
        signals = _tick(strategy, mkt, mid)
    assert signals == []


# ── Needs enough data ────────────────────────────────────────────────────

def test_no_signals_until_lookback_filled():
    strategy = MarketTimingHedge(lookback=10, ema_fast=3, ema_slow=8)
    mkt = _make_market()
    for mid in [0.50, 0.51, 0.52]:  # only 3 ticks, need 8
        signals = _tick(strategy, mkt, mid)
    assert signals == []


# ── Momentum entry ───────────────────────────────────────────────────────

def test_upward_momentum_produces_buy_yes():
    strategy = MarketTimingHedge(
        lookback=15, ema_fast=3, ema_slow=8,
        momentum_threshold=0.005, base_size_usd=10.0, max_leverage=2.0,
    )
    mkt = _make_market()
    # Ramp price up
    prices = [0.40 + i * 0.015 for i in range(15)]
    signals = []
    for p in prices:
        signals = _tick(strategy, mkt, p)

    directional = [s for s in signals if s.metadata.get("reason") == "momentum_entry"]
    assert len(directional) >= 1
    assert directional[0].outcome == "YES"
    assert directional[0].side == Side.BUY


def test_downward_momentum_produces_buy_no():
    strategy = MarketTimingHedge(
        lookback=15, ema_fast=3, ema_slow=8,
        momentum_threshold=0.005, base_size_usd=10.0,
    )
    mkt = _make_market()
    prices = [0.70 - i * 0.015 for i in range(15)]
    signals = []
    for p in prices:
        signals = _tick(strategy, mkt, p)

    directional = [s for s in signals if s.metadata.get("reason") == "momentum_entry"]
    assert len(directional) >= 1
    assert directional[0].outcome == "NO"


# ── Hedging ──────────────────────────────────────────────────────────────

def test_hedge_triggers_on_reversal():
    strategy = MarketTimingHedge(
        lookback=20, ema_fast=3, ema_slow=8,
        momentum_threshold=0.005, hedge_ratio=0.5, base_size_usd=10.0,
    )
    mkt = _make_market()

    # Phase 1: strong uptrend → entry
    for p in [0.40 + i * 0.015 for i in range(12)]:
        _tick(strategy, mkt, p)

    # Phase 2: reversal → momentum fades, should hedge
    signals = []
    for p in [0.58, 0.56, 0.54, 0.52, 0.50, 0.48, 0.46, 0.44]:
        signals = _tick(strategy, mkt, p)
        hedge = [s for s in signals if s.metadata.get("reason") == "hedge"]
        if hedge:
            break

    assert len(hedge) >= 1
    assert hedge[0].outcome == "NO"  # hedging a YES position


# ── Leverage scaling ─────────────────────────────────────────────────────

def test_leverage_scales_with_conviction():
    strategy = MarketTimingHedge(
        lookback=15, ema_fast=3, ema_slow=8,
        momentum_threshold=0.005, base_size_usd=10.0, max_leverage=3.0,
    )
    mkt = _make_market()

    # Strong uptrend → high conviction → size > base
    for p in [0.30 + i * 0.02 for i in range(15)]:
        signals = _tick(strategy, mkt, p)

    entry = [s for s in signals if s.metadata.get("reason") == "momentum_entry"]
    if entry:
        assert entry[0].size > 10.0  # leveraged above base


# ── Metadata for risk ────────────────────────────────────────────────────

def test_signals_carry_strategy_metadata():
    strategy = MarketTimingHedge(
        lookback=10, ema_fast=3, ema_slow=8,
        momentum_threshold=0.001, max_exposure_usd=200.0,
    )
    mkt = _make_market()
    for p in [0.40 + i * 0.02 for i in range(10)]:
        signals = _tick(strategy, mkt, p)

    for s in signals:
        assert s.metadata["strategy"] == "market_timing_hedge"
        assert s.metadata["strategy_exposure_cap"] == 200.0
