"""Tests for the broad crypto strategy."""

import os
os.environ.setdefault("DRY_RUN", "true")
os.environ.setdefault("CRYPTO_STRATEGY_ENABLED", "true")

from polybot.models import Market
from polybot.strategies.crypto_broad import CryptoBroadStrategy, is_crypto_market


def test_is_crypto_market_positive():
    assert is_crypto_market(Market(condition_id="x", question="Will Ethereum hit $10k?")) is True
    assert is_crypto_market(Market(condition_id="x", question="Solana TVL above $50B?")) is True
    assert is_crypto_market(Market(condition_id="x", question="Will Coinbase stock rise?")) is True
    assert is_crypto_market(Market(condition_id="x", question="Dreamcash FDV above $50M?")) is True
    assert is_crypto_market(Market(condition_id="x", question="New DeFi protocol launch?")) is True
    assert is_crypto_market(Market(condition_id="x", question="Crypto regulation bill passes?")) is True


def test_is_crypto_market_excludes_btc():
    """BTC markets should NOT match crypto_broad – they belong to BitcoinStrategy."""
    assert is_crypto_market(Market(condition_id="x", question="Will Bitcoin hit $200k?")) is False
    assert is_crypto_market(Market(condition_id="x", question="BTC ETF inflows rise?")) is False


def test_is_crypto_market_negative():
    assert is_crypto_market(Market(condition_id="x", question="Will it rain tomorrow?")) is False
    assert is_crypto_market(Market(condition_id="x", question="US GDP growth in Q1?")) is False


def test_disabled_returns_nothing(monkeypatch):
    monkeypatch.setattr("polybot.strategies.crypto_broad.settings.crypto_strategy_enabled", False)
    strategy = CryptoBroadStrategy()
    mkt = Market(condition_id="eth1", question="Ethereum above $10k?",
                 token_ids={"YES": "t1", "NO": "t2"})
    for p in [0.40 + i * 0.015 for i in range(20)]:
        strategy.on_tick([mkt], {"midpoints": {mkt.condition_id: p}})
    signals = strategy.on_tick([mkt], {"midpoints": {mkt.condition_id: 0.7}})
    assert signals == []


def test_signals_carry_strategy_name():
    strategy = CryptoBroadStrategy()
    strategy.ema_slow = 8
    strategy.ema_fast = 3
    strategy.momentum_threshold = 0.001
    strategy.lookback = 10
    strategy._states.clear()
    strategy._states.default_factory = lambda: __import__("polybot.strategies.crypto_broad", fromlist=["_CryptoMarketState"])._CryptoMarketState(
        history=__import__("collections").deque(maxlen=10)
    )

    mkt = Market(condition_id="eth1", question="Ethereum above $10k?",
                 token_ids={"YES": "t1", "NO": "t2"})
    for p in [0.40 + i * 0.02 for i in range(10)]:
        signals = strategy.on_tick([mkt], {"midpoints": {mkt.condition_id: p}})

    for s in signals:
        assert s.metadata["strategy"] == "crypto_broad"
