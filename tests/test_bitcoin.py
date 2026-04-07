"""Tests for the Bitcoin strategy."""

import os
os.environ.setdefault("DRY_RUN", "true")
os.environ.setdefault("BTC_STRATEGY_ENABLED", "true")

from polybot.models import Market, Side
from polybot.strategies.bitcoin import BitcoinStrategy, is_btc_market


def _btc_market(cid: str = "btc1") -> Market:
    return Market(condition_id=cid, question="Will Bitcoin hit $200k in 2026?",
                  token_ids={"YES": "tok1", "NO": "tok2"})


def _non_btc_market() -> Market:
    return Market(condition_id="other", question="Will it rain tomorrow?",
                  token_ids={"YES": "tok3", "NO": "tok4"})


def _tick(strategy, mkt, mid):
    return strategy.on_tick([mkt], {"midpoints": {mkt.condition_id: mid}})


def test_is_btc_market_positive():
    assert is_btc_market(_btc_market()) is True
    assert is_btc_market(Market(condition_id="x", question="BTC ETF inflows")) is True
    assert is_btc_market(Market(condition_id="x", question="Will Satoshi move coins?")) is True


def test_is_btc_market_negative():
    assert is_btc_market(_non_btc_market()) is False
    assert is_btc_market(Market(condition_id="x", question="Ethereum price above $5k")) is False


def test_ignores_non_btc_markets():
    strategy = BitcoinStrategy()
    mkt = _non_btc_market()
    for p in [0.5 + i * 0.01 for i in range(20)]:
        signals = _tick(strategy, mkt, p)
    assert signals == []


def test_btc_momentum_entry(monkeypatch):
    monkeypatch.setattr("polybot.strategies.bitcoin.settings.btc_strategy_enabled", True)
    strategy = BitcoinStrategy()
    # Override for test speed
    strategy.ema_slow = 8
    strategy.ema_fast = 3
    strategy.momentum_threshold = 0.005
    strategy.lookback = 15
    strategy._states.clear()
    strategy._states.default_factory = lambda: __import__("polybot.strategies.bitcoin", fromlist=["_BTCMarketState"])._BTCMarketState(
        history=__import__("collections").deque(maxlen=15)
    )

    mkt = _btc_market()
    signals = []
    for p in [0.40 + i * 0.015 for i in range(15)]:
        signals = _tick(strategy, mkt, p)

    entries = [s for s in signals if s.metadata.get("reason") == "btc_momentum"]
    assert len(entries) >= 1
    assert entries[0].outcome == "YES"
    assert entries[0].side == Side.BUY


def test_disabled_returns_nothing(monkeypatch):
    monkeypatch.setattr("polybot.strategies.bitcoin.settings.btc_strategy_enabled", False)
    strategy = BitcoinStrategy()
    mkt = _btc_market()
    for p in [0.40 + i * 0.015 for i in range(20)]:
        signals = _tick(strategy, mkt, p)
    assert signals == []


def test_signals_carry_metadata():
    strategy = BitcoinStrategy()
    strategy.ema_slow = 8
    strategy.ema_fast = 3
    strategy.momentum_threshold = 0.001
    strategy.lookback = 10
    strategy._states.clear()
    strategy._states.default_factory = lambda: __import__("polybot.strategies.bitcoin", fromlist=["_BTCMarketState"])._BTCMarketState(
        history=__import__("collections").deque(maxlen=10)
    )

    mkt = _btc_market()
    for p in [0.40 + i * 0.02 for i in range(10)]:
        signals = _tick(strategy, mkt, p)

    for s in signals:
        assert s.metadata["strategy"] == "bitcoin"
