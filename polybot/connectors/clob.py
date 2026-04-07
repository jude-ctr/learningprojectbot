"""Thin wrapper around the Polymarket CLOB client.

Keeps all API specifics in one place so the rest of the bot stays decoupled.
Swap this out or subclass it to support other prediction-market protocols.
"""

from __future__ import annotations

import logging
from typing import Any

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs

from polybot.config import settings
from polybot.models import Signal

logger = logging.getLogger(__name__)


class PolymarketConnector:
    """Manages authentication and order lifecycle against Polymarket's CLOB.

    Read-only operations (market data, orderbook) work without a private key.
    Write operations (place/cancel orders) require a valid PRIVATE_KEY in .env.
    Credential derivation is deferred until the first write operation.
    """

    def __init__(self) -> None:
        self._client = ClobClient(
            host="https://clob.polymarket.com",
            key=settings.polymarket_api_key or "",
            chain_id=settings.chain_id,
            signature_type=2,  # POLY_GNOSIS_SAFE
            funder=settings.private_key or None,
        )
        self._authenticated = False

        # Only derive creds if a private key is available
        if settings.private_key:
            self._authenticate()
        else:
            logger.warning(
                "No PRIVATE_KEY configured – running in read-only / dry-run mode. "
                "Set PRIVATE_KEY in .env to enable live trading."
            )
        logger.info("PolymarketConnector initialised (dry_run=%s, authenticated=%s)",
                     settings.dry_run, self._authenticated)

    def _authenticate(self) -> None:
        """Derive and set API credentials from the private key."""
        try:
            creds = self._client.create_or_derive_api_creds()
            self._client.set_api_creds(creds)
            self._authenticated = True
        except Exception:
            logger.exception("Failed to derive API credentials – write operations will be unavailable")
            self._authenticated = False

    # ── Market data (no auth required) ───────────────────────────────────

    def get_markets(self, *, limit: int = 50, active_only: bool = True) -> list[dict[str, Any]]:
        """Fetch available markets from the CLOB.

        The raw API returns a paginated dict like ``{"data": [...], "next_cursor": "..."}``.
        We unwrap it and return just the list of market dicts.
        """
        resp = self._client.get_markets(next_cursor="MA==")
        # Handle both paginated dict response and bare list
        if isinstance(resp, dict):
            return resp.get("data", [])
        if isinstance(resp, list):
            return resp
        logger.warning("Unexpected get_markets response type: %s", type(resp))
        return []

    def get_orderbook(self, token_id: str) -> dict[str, Any]:
        return self._client.get_order_book(token_id)

    def get_midpoint(self, token_id: str) -> float:
        return float(self._client.get_midpoint(token_id))

    # ── Order management (auth required) ─────────────────────────────────

    def place_order(self, signal: Signal) -> dict[str, Any] | None:
        """Translate a Signal into a CLOB order.  Returns API response or None if dry-run."""
        token_id = signal.market.token_ids.get(signal.outcome)
        if token_id is None:
            logger.error("No token_id for outcome=%s in market=%s", signal.outcome, signal.market.condition_id)
            return None

        if settings.dry_run:
            logger.info("[DRY RUN] Would place %s %s @ %.4f x $%.2f on %s",
                        signal.side.value, signal.outcome, signal.price, signal.size, signal.market.question)
            return {"dry_run": True, "signal": signal}

        if not self._authenticated:
            logger.error("Cannot place order – no valid credentials. Set PRIVATE_KEY in .env.")
            return None

        order_args = OrderArgs(
            price=signal.price,
            size=signal.size,
            side=signal.side.value,
            token_id=token_id,
        )
        signed = self._client.create_and_sign_order(order_args)
        resp = self._client.post_order(signed, signal.order_type.value)
        logger.info("Order placed: %s", resp)
        return resp

    def cancel_order(self, order_id: str) -> dict[str, Any] | None:
        if not self._authenticated:
            logger.error("Cannot cancel order – no valid credentials.")
            return None
        return self._client.cancel(order_id)

    def cancel_all(self) -> dict[str, Any] | None:
        if not self._authenticated:
            logger.error("Cannot cancel orders – no valid credentials.")
            return None
        return self._client.cancel_all()

    def get_open_orders(self) -> list[dict[str, Any]]:
        if not self._authenticated:
            logger.error("Cannot fetch orders – no valid credentials.")
            return []
        return self._client.get_orders()
