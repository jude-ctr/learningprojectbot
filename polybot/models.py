"""Domain models shared across the bot."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


@dataclass(frozen=True)
class Market:
    """A single Polymarket binary (yes/no) market."""
    condition_id: str
    question: str
    token_ids: dict[str, str] = field(default_factory=dict)  # {"YES": ..., "NO": ...}
    active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Signal:
    """Output of a Strategy – a suggested trade intent."""
    market: Market
    side: Side
    outcome: str          # "YES" or "NO"
    price: float          # limit price (0-1)
    size: float           # USD notional
    order_type: OrderType = OrderType.LIMIT
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Position:
    """Tracks a live position."""
    market: Market
    outcome: str
    size: float
    avg_entry: float
    unrealised_pnl: float = 0.0
