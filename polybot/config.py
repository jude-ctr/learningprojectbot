"""Centralised configuration loaded from env / .env file.

Uses python-dotenv to load .env, then reads os.environ.
No pydantic-settings dependency required.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Search for .env in multiple likely locations
_candidates = [
    Path.cwd() / ".env",                                    # current working directory
    Path(__file__).resolve().parent.parent / ".env",         # project root (relative to this file)
    Path(__file__).resolve().parent / ".env",                # polybot/ dir (in case)
]

_loaded_from = None
for _candidate in _candidates:
    if _candidate.is_file():
        load_dotenv(_candidate, override=True)
        _loaded_from = str(_candidate)
        break

if _loaded_from:
    print(f"[polybot] Loaded .env from: {_loaded_from}", file=sys.stderr)
else:
    print(f"[polybot] WARNING: No .env file found. Searched:", file=sys.stderr)
    for c in _candidates:
        print(f"  - {c} (exists={c.is_file()})", file=sys.stderr)


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_bool(key: str, default: bool = False) -> bool:
    return _env(key, str(default)).lower() in ("true", "1", "yes")


def _env_int(key: str, default: int = 0) -> int:
    return int(_env(key, str(default)))


def _env_float(key: str, default: float = 0.0) -> float:
    return float(_env(key, str(default)))


@dataclass
class Settings:
    """All tunables live here.  Extend freely — validated on startup."""

    # ── Polymarket CLOB credentials ──────────────────────────────────────
    polymarket_api_key: str = field(default_factory=lambda: _env("POLYMARKET_API_KEY"))
    polymarket_secret: str = field(default_factory=lambda: _env("POLYMARKET_SECRET"))
    polymarket_passphrase: str = field(default_factory=lambda: _env("POLYMARKET_PASSPHRASE"))
    private_key: str = field(default_factory=lambda: _env("PRIVATE_KEY"))

    # ── Chain / network ──────────────────────────────────────────────────
    chain_id: int = field(default_factory=lambda: _env_int("CHAIN_ID", 137))

    # ── Runtime behaviour ────────────────────────────────────────────────
    dry_run: bool = field(default_factory=lambda: _env_bool("DRY_RUN", True))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
    tick_interval_seconds: float = field(default_factory=lambda: _env_float("TICK_INTERVAL_SECONDS", 10.0))

    # ── Risk limits (override per-strategy via strategy config) ─────────
    max_position_size_usd: float = field(default_factory=lambda: _env_float("MAX_POSITION_SIZE_USD", 100.0))
    max_open_orders: int = field(default_factory=lambda: _env_int("MAX_OPEN_ORDERS", 10))

    # ── Trade sizing mode ───────────────────────────────────────────────
    # "fixed"   = use *_BASE_SIZE_USD values directly (default)
    # "percent" = compute trade size as a percentage of wallet balance
    trade_size_mode: str = field(default_factory=lambda: _env("TRADE_SIZE_MODE", "fixed"))

    # ── Shutdown behaviour ──────────────────────────────────────────────
    cancel_on_shutdown: bool = field(default_factory=lambda: _env_bool("CANCEL_ON_SHUTDOWN", True))

    # ── Market scope (controls which markets the bot trades) ─────────────
    # Options: "all", "btc", "crypto", "btc+crypto"
    # "all"        = every market on Polymarket
    # "btc"        = only Bitcoin-related markets
    # "crypto"     = only crypto markets (BTC + altcoins/DeFi/etc)
    # "btc+crypto" = same as "crypto" (explicit alias)
    market_scope: str = field(default_factory=lambda: _env("MARKET_SCOPE", "all"))

    # ── Market-timing hedge strategy ─────────────────────────────────────
    market_timing_enabled: bool = field(default_factory=lambda: _env_bool("MARKET_TIMING_ENABLED", True))
    # Scope: "all", "btc", "crypto" – which markets this strategy runs on
    market_timing_scope: str = field(default_factory=lambda: _env("MARKET_TIMING_SCOPE", "all"))
    market_timing_lookback: int = field(default_factory=lambda: _env_int("MARKET_TIMING_LOOKBACK", 20))
    market_timing_ema_fast: int = field(default_factory=lambda: _env_int("MARKET_TIMING_EMA_FAST", 5))
    market_timing_ema_slow: int = field(default_factory=lambda: _env_int("MARKET_TIMING_EMA_SLOW", 15))
    market_timing_momentum_threshold: float = field(default_factory=lambda: _env_float("MARKET_TIMING_MOMENTUM_THRESHOLD", 0.02))
    market_timing_hedge_ratio: float = field(default_factory=lambda: _env_float("MARKET_TIMING_HEDGE_RATIO", 0.5))
    market_timing_base_size_usd: float = field(default_factory=lambda: _env_float("MARKET_TIMING_BASE_SIZE_USD", 10.0))
    market_timing_base_size_pct: float = field(default_factory=lambda: _env_float("MARKET_TIMING_BASE_SIZE_PCT", 2.0))
    market_timing_max_leverage: float = field(default_factory=lambda: _env_float("MARKET_TIMING_MAX_LEVERAGE", 3.0))
    market_timing_max_exposure_usd: float = field(default_factory=lambda: _env_float("MARKET_TIMING_MAX_EXPOSURE_USD", 500.0))
    market_timing_max_exposure_pct: float = field(default_factory=lambda: _env_float("MARKET_TIMING_MAX_EXPOSURE_PCT", 20.0))
    market_timing_max_positions: int = field(default_factory=lambda: _env_int("MARKET_TIMING_MAX_POSITIONS", 5))
    market_timing_candle_ticks: int = field(default_factory=lambda: _env_int("MARKET_TIMING_CANDLE_TICKS", 30))
    market_timing_candle_threshold: float = field(default_factory=lambda: _env_float("MARKET_TIMING_CANDLE_THRESHOLD", 0.01))

    # ── Midpoint spread strategy ─────────────────────────────────────────
    spread_enabled: bool = field(default_factory=lambda: _env_bool("SPREAD_ENABLED", True))

    # ── Bitcoin strategy ─────────────────────────────────────────────────
    btc_strategy_enabled: bool = field(default_factory=lambda: _env_bool("BTC_STRATEGY_ENABLED", True))
    btc_base_size_usd: float = field(default_factory=lambda: _env_float("BTC_BASE_SIZE_USD", 15.0))
    btc_base_size_pct: float = field(default_factory=lambda: _env_float("BTC_BASE_SIZE_PCT", 3.0))
    btc_max_leverage: float = field(default_factory=lambda: _env_float("BTC_MAX_LEVERAGE", 3.0))
    btc_max_exposure_usd: float = field(default_factory=lambda: _env_float("BTC_MAX_EXPOSURE_USD", 500.0))
    btc_max_exposure_pct: float = field(default_factory=lambda: _env_float("BTC_MAX_EXPOSURE_PCT", 25.0))
    btc_momentum_threshold: float = field(default_factory=lambda: _env_float("BTC_MOMENTUM_THRESHOLD", 0.015))
    btc_ema_fast: int = field(default_factory=lambda: _env_int("BTC_EMA_FAST", 4))
    btc_ema_slow: int = field(default_factory=lambda: _env_int("BTC_EMA_SLOW", 12))
    btc_lookback: int = field(default_factory=lambda: _env_int("BTC_LOOKBACK", 20))
    btc_hedge_ratio: float = field(default_factory=lambda: _env_float("BTC_HEDGE_RATIO", 0.6))
    btc_candle_ticks: int = field(default_factory=lambda: _env_int("BTC_CANDLE_TICKS", 30))           # 30×10s = 5 min
    btc_candle_threshold: float = field(default_factory=lambda: _env_float("BTC_CANDLE_THRESHOLD", 0.01))  # 1% move

    # ── Crypto broad strategy ────────────────────────────────────────────
    crypto_strategy_enabled: bool = field(default_factory=lambda: _env_bool("CRYPTO_STRATEGY_ENABLED", True))
    crypto_base_size_usd: float = field(default_factory=lambda: _env_float("CRYPTO_BASE_SIZE_USD", 10.0))
    crypto_base_size_pct: float = field(default_factory=lambda: _env_float("CRYPTO_BASE_SIZE_PCT", 2.0))
    crypto_max_leverage: float = field(default_factory=lambda: _env_float("CRYPTO_MAX_LEVERAGE", 2.5))
    crypto_max_exposure_usd: float = field(default_factory=lambda: _env_float("CRYPTO_MAX_EXPOSURE_USD", 400.0))
    crypto_max_exposure_pct: float = field(default_factory=lambda: _env_float("CRYPTO_MAX_EXPOSURE_PCT", 20.0))
    crypto_momentum_threshold: float = field(default_factory=lambda: _env_float("CRYPTO_MOMENTUM_THRESHOLD", 0.02))
    crypto_ema_fast: int = field(default_factory=lambda: _env_int("CRYPTO_EMA_FAST", 5))
    crypto_ema_slow: int = field(default_factory=lambda: _env_int("CRYPTO_EMA_SLOW", 15))
    crypto_lookback: int = field(default_factory=lambda: _env_int("CRYPTO_LOOKBACK", 20))
    crypto_hedge_ratio: float = field(default_factory=lambda: _env_float("CRYPTO_HEDGE_RATIO", 0.4))
    crypto_candle_ticks: int = field(default_factory=lambda: _env_int("CRYPTO_CANDLE_TICKS", 30))
    crypto_candle_threshold: float = field(default_factory=lambda: _env_float("CRYPTO_CANDLE_THRESHOLD", 0.01))

    # ── Confluence mode ──────────────────────────────────────────────────
    confluence_enabled: bool = field(default_factory=lambda: _env_bool("CONFLUENCE_ENABLED", False))
    confluence_min_agree: int = field(default_factory=lambda: _env_int("CONFLUENCE_MIN_AGREE", 2))
    confluence_size_boost: float = field(default_factory=lambda: _env_float("CONFLUENCE_SIZE_BOOST", 1.5))


# Singleton – import this everywhere
settings = Settings()

# Startup sanity check
_pk_status = "SET (length={})".format(len(settings.private_key)) if settings.private_key else "EMPTY"
print(f"[polybot] Config: PRIVATE_KEY={_pk_status}, DRY_RUN={settings.dry_run}", file=sys.stderr)
