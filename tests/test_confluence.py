"""Tests for the confluence filter."""

import os
os.environ.setdefault("DRY_RUN", "true")

from polybot.models import Market, OrderType, Side, Signal
from polybot.strategies.confluence import ConfluenceFilter


def _mkt(cid="m1"):
    return Market(condition_id=cid, question="Test?", token_ids={"YES": "t1", "NO": "t2"})


def _sig(cid="m1", side=Side.BUY, outcome="YES", size=10.0, strategy="alpha"):
    return Signal(
        market=_mkt(cid), side=side, outcome=outcome, price=0.5, size=size,
        order_type=OrderType.LIMIT, metadata={"strategy": strategy},
    )


def test_passthrough_when_disabled(monkeypatch):
    monkeypatch.setattr("polybot.strategies.confluence.settings.confluence_enabled", False)
    cf = ConfluenceFilter()
    cf.add_signals("alpha", [_sig(strategy="alpha")])
    cf.add_signals("beta", [_sig(strategy="beta")])
    result = cf.resolve()
    assert len(result) == 2  # both pass through


def test_filters_when_enabled(monkeypatch):
    monkeypatch.setattr("polybot.strategies.confluence.settings.confluence_enabled", True)
    monkeypatch.setattr("polybot.strategies.confluence.settings.confluence_min_agree", 2)
    monkeypatch.setattr("polybot.strategies.confluence.settings.confluence_size_boost", 1.5)

    cf = ConfluenceFilter()
    cf.min_agree = 2
    cf.size_boost = 1.5

    # Only alpha agrees on m1 BUY YES – should be filtered out
    cf.add_signals("alpha", [_sig(cid="m1", strategy="alpha")])
    # Both alpha and beta agree on m2 BUY YES
    cf.add_signals("alpha", [_sig(cid="m2", strategy="alpha", size=10.0)])
    cf.add_signals("beta", [_sig(cid="m2", strategy="beta", size=8.0)])

    result = cf.resolve()
    assert len(result) == 1
    assert result[0].market.condition_id == "m2"
    assert result[0].size == 15.0  # 10.0 * 1.5 boost
    assert result[0].metadata["confluence"] is True
    assert result[0].metadata["confluence_count"] == 2


def test_different_directions_dont_confluence(monkeypatch):
    monkeypatch.setattr("polybot.strategies.confluence.settings.confluence_enabled", True)
    monkeypatch.setattr("polybot.strategies.confluence.settings.confluence_min_agree", 2)
    monkeypatch.setattr("polybot.strategies.confluence.settings.confluence_size_boost", 1.5)

    cf = ConfluenceFilter()
    cf.min_agree = 2
    cf.size_boost = 1.5

    # Alpha buys YES, beta buys NO – different directions, no confluence
    cf.add_signals("alpha", [_sig(cid="m1", outcome="YES", strategy="alpha")])
    cf.add_signals("beta", [_sig(cid="m1", outcome="NO", strategy="beta")])

    result = cf.resolve()
    assert len(result) == 0


def test_reset_clears_state():
    cf = ConfluenceFilter()
    cf.add_signals("alpha", [_sig()])
    cf.reset()
    assert len(cf._all_signals) == 0
    assert len(cf._buckets) == 0
