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
        # ClobClient's 'key' param is the private key (not an API key).
        # Pass None when empty to avoid hex parsing errors.
        private_key = settings.private_key if settings.private_key else None

        self._client = ClobClient(
            host="https://clob.polymarket.com",
            key=private_key,
            chain_id=settings.chain_id,
            signature_type=2,  # POLY_GNOSIS_SAFE
            funder=private_key,
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

    def get_markets(self, *, max_pages: int = 10) -> list[dict[str, Any]]:
        """Fetch available markets from the CLOB, paginating until we find open ones.

        The API returns oldest markets first, so page 1 is mostly closed.
        We paginate forward and collect markets where accepting_orders=True.
        """
        import json

        all_markets: list[dict[str, Any]] = []
        cursor = "MA=="

        for page in range(max_pages):
            resp = self._client.get_markets(next_cursor=cursor)
            raw_list, next_cursor = self._unwrap_response(resp)

            for item in raw_list:
                market = self._parse_market_item(item)
                if market is not None:
                    all_markets.append(market)

            logger.debug("Page %d: got %d items, cursor=%s", page + 1, len(raw_list), next_cursor)

            # Stop if no more pages
            if not next_cursor or next_cursor == cursor or next_cursor == "LTE=":
                break
            cursor = next_cursor

        logger.info("Fetched %d markets across %d page(s)", len(all_markets), page + 1)
        return all_markets

    @staticmethod
    def _unwrap_response(resp: Any) -> tuple[list, str | None]:
        """Extract the data list and next_cursor from a CLOB API response."""
        import json

        if isinstance(resp, dict):
            return resp.get("data", []), resp.get("next_cursor")
        if isinstance(resp, list):
            return resp, None
        if isinstance(resp, str):
            try:
                parsed = json.loads(resp)
                if isinstance(parsed, dict):
                    return parsed.get("data", []), parsed.get("next_cursor")
                return parsed, None
            except (json.JSONDecodeError, AttributeError):
                logger.error("Cannot parse response: %.200s", resp)
        return [], None

    @staticmethod
    def _parse_market_item(item: Any) -> dict[str, Any] | None:
        """Ensure a market item is a dict (handles JSON-string items)."""
        import json

        if isinstance(item, dict):
            return item
        if isinstance(item, str):
            try:
                parsed = json.loads(item)
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                pass
        return None

    def get_orderbook(self, token_id: str) -> dict[str, Any]:
        return self._client.get_order_book(token_id)

    def get_midpoint(self, token_id: str) -> float | None:
        """Get the midpoint price for a token.  Returns None if unavailable (404 / no book)."""
        try:
            result = self._client.get_midpoint(token_id)
            mid = float(result)
            if mid <= 0 or mid >= 1:
                return None
            return mid
        except Exception as exc:
            # 404 = resolved/no-book market, not worth logging at warning level
            exc_str = str(exc)
            if "404" in exc_str or "not found" in exc_str.lower():
                logger.debug("No midpoint for token %s (404 – likely resolved)", token_id[:16])
            else:
                logger.debug("Could not fetch midpoint for token %s: %s", token_id[:16], exc)
            return None

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
