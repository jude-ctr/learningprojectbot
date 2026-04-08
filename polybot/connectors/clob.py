"""Thin wrapper around the Polymarket CLOB client.

Keeps all API specifics in one place so the rest of the bot stays decoupled.
Swap this out or subclass it to support other prediction-market protocols.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BookParams, OrderArgs

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
        private_key = settings.private_key if settings.private_key else None

        self._client = ClobClient(
            host="https://clob.polymarket.com",
            key=private_key,
            chain_id=settings.chain_id,
            signature_type=2,  # POLY_GNOSIS_SAFE
            funder=private_key,
        )
        self._authenticated = False

        if settings.private_key:
            try:
                from eth_account import Account
                acct = Account.from_key(settings.private_key)
                logger.info("Wallet address: %s", acct.address)
            except Exception:
                pass
            self._authenticate()
        else:
            logger.warning(
                "No PRIVATE_KEY configured – running in read-only / dry-run mode. "
                "Set PRIVATE_KEY in .env to enable live trading."
            )
        logger.info("PolymarketConnector initialised (dry_run=%s, authenticated=%s)",
                     settings.dry_run, self._authenticated)

    def _authenticate(self) -> None:
        try:
            creds = self._client.create_or_derive_api_creds()
            self._client.set_api_creds(creds)
            self._authenticated = True
        except Exception:
            logger.exception("Failed to derive API credentials – write operations will be unavailable")
            self._authenticated = False

    # ── Wallet balance ────────────────────────────────────────────────────

    def get_usdc_balance(self) -> float | None:
        """Fetch the wallet's USDC collateral balance from Polymarket."""
        if not self._authenticated:
            logger.warning("Cannot fetch balance – not authenticated")
            return None
        try:
            from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
            params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            resp = self._client.get_balance_allowance(params)
            logger.info("Balance API raw response: %s", resp)

            if isinstance(resp, str):
                import json
                try:
                    resp = json.loads(resp)
                except (json.JSONDecodeError, ValueError):
                    pass

            if isinstance(resp, dict):
                # Try multiple possible key names
                raw = None
                for key in ("balance", "Balance", "amount", "collateral", "available"):
                    if key in resp:
                        raw = resp[key]
                        break
                if raw is None and len(resp) > 0:
                    # Log all keys so we can see the structure
                    logger.info("Balance response keys: %s", list(resp.keys()))
                    # Try first numeric-looking value
                    for k, v in resp.items():
                        try:
                            raw = float(v)
                            logger.info("Using key '%s' = %s as balance", k, v)
                            break
                        except (ValueError, TypeError):
                            continue

                if raw is not None:
                    balance = float(raw)
                    # USDC has 6 decimals on Polygon — API may return raw units
                    if balance > 1_000_000:
                        balance = balance / 1e6
                    return balance

            logger.warning("Could not parse balance from response: %s (type=%s)", resp, type(resp).__name__)
            return None
        except ImportError:
            logger.debug("BalanceAllowanceParams not available in this py-clob-client version")
            return None
        except Exception:
            logger.exception("Failed to fetch USDC balance")
            return None

    # ── Market data (no auth required) ───────────────────────────────────

    def get_markets(self, *, max_pages: int = 2) -> list[dict[str, Any]]:
        """Fetch actively-traded markets using the sampling endpoint.

        Uses get_sampling_markets which returns only markets with live
        liquidity, avoiding the 10k+ closed markets from the full endpoint.
        Falls back to the full endpoint if sampling returns nothing.
        """
        markets = self._fetch_sampling_markets(max_pages)
        if markets:
            return markets

        logger.info("Sampling endpoint returned 0 markets – falling back to full endpoint")
        return self._fetch_all_markets(max_pages)

    def _fetch_sampling_markets(self, max_pages: int) -> list[dict[str, Any]]:
        """Fetch from /sampling-markets – only actively-traded markets."""
        all_markets: list[dict[str, Any]] = []
        cursor = "MA=="

        for page in range(max_pages):
            try:
                resp = self._client.get_sampling_markets(next_cursor=cursor)
            except Exception:
                logger.debug("Sampling markets request failed on page %d", page + 1)
                break

            raw_list, next_cursor = self._unwrap_response(resp)

            for item in raw_list:
                market = self._parse_market_item(item)
                if market is not None:
                    all_markets.append(market)

            if not next_cursor or next_cursor == cursor or next_cursor == "LTE=":
                break
            cursor = next_cursor

        logger.info("Sampling endpoint: fetched %d markets across %d page(s)",
                     len(all_markets), page + 1)
        return all_markets

    def _fetch_all_markets(self, max_pages: int) -> list[dict[str, Any]]:
        """Fallback: paginate the full /markets endpoint."""
        all_markets: list[dict[str, Any]] = []
        cursor = "MA=="

        for page in range(max_pages):
            resp = self._client.get_markets(next_cursor=cursor)
            raw_list, next_cursor = self._unwrap_response(resp)

            for item in raw_list:
                market = self._parse_market_item(item)
                if market is not None:
                    all_markets.append(market)

            if not next_cursor or next_cursor == cursor or next_cursor == "LTE=":
                break
            cursor = next_cursor

        logger.info("Full endpoint: fetched %d markets across %d page(s)",
                     len(all_markets), page + 1)
        return all_markets

    @staticmethod
    def _unwrap_response(resp: Any) -> tuple[list, str | None]:
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
        """Get the midpoint price for a token.  Returns None if unavailable."""
        try:
            result = self._client.get_midpoint(token_id)
            mid = self._extract_price(result)
            if mid is not None and 0 < mid < 1:
                return mid
            return None
        except Exception:
            return None

    @staticmethod
    def _extract_price(value: Any) -> float | None:
        """Extract a float price from various response formats.

        The API may return:
          - A bare float/string: "0.55" or 0.55
          - A dict: {"mid": "0.55"} or {"price": "0.55"}
        """
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        if isinstance(value, dict):
            # Try common key names
            for key in ("mid", "price", "midpoint"):
                raw = value.get(key)
                if raw is not None:
                    try:
                        return float(raw)
                    except (ValueError, TypeError):
                        pass
        return None

    def get_prices_batch(self, token_ids: list[str]) -> dict[str, float]:
        """Fetch prices for multiple tokens in a single request.

        Chunks into batches of 100 to avoid 400 errors from oversized payloads.
        """
        if not token_ids:
            return {}

        prices: dict[str, float] = {}
        chunk_size = 100

        for i in range(0, len(token_ids), chunk_size):
            chunk = token_ids[i:i + chunk_size]
            params = [BookParams(token_id=tid, side="buy") for tid in chunk]
            try:
                resp = self._client.get_prices(params)
            except Exception:
                logger.debug("Batch price fetch failed for chunk %d", i // chunk_size)
                continue

            self._merge_batch_prices(prices, resp, chunk)

        return prices

    def get_last_trade_prices_batch(self, token_ids: list[str]) -> dict[str, float]:
        """Fetch last trade prices for multiple tokens in a single request."""
        if not token_ids:
            return {}

        prices: dict[str, float] = {}
        chunk_size = 100

        for i in range(0, len(token_ids), chunk_size):
            chunk = token_ids[i:i + chunk_size]
            params = [BookParams(token_id=tid) for tid in chunk]
            try:
                resp = self._client.get_last_trades_prices(params)
            except Exception:
                logger.debug("Batch last-trade-price fetch failed for chunk %d", i // chunk_size)
                continue

            self._merge_batch_prices(prices, resp, chunk)

        return prices

    def _merge_batch_prices(self, prices: dict[str, float], resp: Any, token_ids: list[str]) -> None:
        """Parse a batch price response and merge into the prices dict."""
        if isinstance(resp, dict):
            for tid, val in resp.items():
                p = self._extract_price(val)
                if p is not None and 0 < p < 1:
                    prices[tid] = p
        elif isinstance(resp, list):
            for i, item in enumerate(resp):
                if i < len(token_ids):
                    p = self._extract_price(item)
                    if p is not None and 0 < p < 1:
                        prices[token_ids[i]] = p

    # ── Order management (auth required) ─────────────────────────────────

    def place_order(self, signal: Signal) -> dict[str, Any] | None:
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
