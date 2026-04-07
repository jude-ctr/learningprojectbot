"""Tests for the risk manager."""

from polybot.models import Market, OrderType, Side, Signal
from polybot.risk.manager import RiskManager


def _make_signal(price: float = 0.5, size: float = 10.0, strategy: str | None = None,
                 cap: float | None = None) -> Signal:
    mkt = Market(condition_id="abc", question="Test?", token_ids={"YES": "tok1"})
    meta = {}
    if strategy:
        meta["strategy"] = strategy
    if cap is not None:
        meta["strategy_exposure_cap"] = cap
    return Signal(market=mkt, side=Side.BUY, outcome="YES", price=price, size=size, metadata=meta)


def test_signal_passes_basic_checks():
    rm = RiskManager()
    assert rm.check(_make_signal()) is True


def test_rejects_oversized_order():
    rm = RiskManager()
    assert rm.check(_make_signal(size=999_999)) is False


def test_rejects_invalid_price():
    rm = RiskManager()
    assert rm.check(_make_signal(price=1.5)) is False
    assert rm.check(_make_signal(price=-0.1)) is False


def test_rejects_when_max_orders_reached():
    rm = RiskManager(open_order_count=10)
    assert rm.check(_make_signal()) is False


def test_per_strategy_exposure_cap():
    rm = RiskManager()
    sig1 = _make_signal(size=40.0, strategy="alpha", cap=50.0)
    assert rm.check(sig1) is True
    rm.record_order(sig1)

    # Second order would push over cap
    sig2 = _make_signal(size=20.0, strategy="alpha", cap=50.0)
    assert rm.check(sig2) is False


def test_different_strategies_independent_caps():
    rm = RiskManager()
    sig_a = _make_signal(size=40.0, strategy="alpha", cap=50.0)
    rm.record_order(sig_a)
    assert rm.check(sig_a) is False  # 40 + 40 = 80 > cap 50

    # beta has its own independent budget — 40 is fine under beta's 50 cap
    sig_b = _make_signal(size=40.0, strategy="beta", cap=50.0)
    assert rm.check(sig_b) is True


def test_record_cancel_reduces_exposure():
    rm = RiskManager()
    sig = _make_signal(size=30.0, strategy="alpha", cap=100.0)
    rm.record_order(sig)
    assert rm.get_strategy_exposure("alpha") == 30.0

    rm.record_cancel(strategy_name="alpha", size=30.0)
    assert rm.get_strategy_exposure("alpha") == 0.0
