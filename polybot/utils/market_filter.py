"""Shared market filtering utilities.

Centralises the logic for scoping which markets a strategy or the
entire bot should operate on.  Used by the engine (global scope)
and by individual strategies (per-strategy scope).
"""

from __future__ import annotations

from polybot.models import Market
from polybot.strategies.bitcoin import is_btc_market
from polybot.strategies.crypto_broad import is_crypto_market


def filter_by_scope(markets: list[Market], scope: str) -> list[Market]:
    """Filter markets by scope string.

    Scopes:
        "all"        → no filtering, return everything
        "btc"        → only Bitcoin-related markets
        "crypto"     → BTC + altcoin/DeFi/exchange markets
        "btc+crypto" → alias for "crypto"
        "non_btc_crypto" → crypto excluding BTC
    """
    scope = scope.lower().strip()

    if scope == "all":
        return markets
    elif scope == "btc":
        return [m for m in markets if is_btc_market(m)]
    elif scope in ("crypto", "btc+crypto"):
        return [m for m in markets if is_btc_market(m) or is_crypto_market(m)]
    elif scope == "non_btc_crypto":
        return [m for m in markets if is_crypto_market(m)]
    else:
        return markets
