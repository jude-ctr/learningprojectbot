"""Smoke tests for the risk manager."""

from polybot.models import Market, OrderType, Side, Signal
from polybot.risk.manager import RiskManager


def _make_signal(price: float = 0.5, size: float = 10.0) -> Signal:
    mkt = Market(condition_id="abc", question="Test?", token_ids={"YES": "tok1"})
    return Signal(market=mkt, side=Side.BUY, outcome="YES", price=price, size=size)


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
