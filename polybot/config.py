"""Centralised configuration loaded from env / .env file.

Uses python-dotenv to load .env, then reads os.environ.
No pydantic-settings dependency required.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (if it exists)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


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

    # ── Market-timing hedge strategy ─────────────────────────────────────
    market_timing_enabled: bool = field(default_factory=lambda: _env_bool("MARKET_TIMING_ENABLED", True))
    market_timing_lookback: int = field(default_factory=lambda: _env_int("MARKET_TIMING_LOOKBACK", 20))
    market_timing_ema_fast: int = field(default_factory=lambda: _env_int("MARKET_TIMING_EMA_FAST", 5))
    market_timing_ema_slow: int = field(default_factory=lambda: _env_int("MARKET_TIMING_EMA_SLOW", 15))
    market_timing_momentum_threshold: float = field(default_factory=lambda: _env_float("MARKET_TIMING_MOMENTUM_THRESHOLD", 0.02))
    market_timing_hedge_ratio: float = field(default_factory=lambda: _env_float("MARKET_TIMING_HEDGE_RATIO", 0.5))
    market_timing_base_size_usd: float = field(default_factory=lambda: _env_float("MARKET_TIMING_BASE_SIZE_USD", 10.0))
    market_timing_max_leverage: float = field(default_factory=lambda: _env_float("MARKET_TIMING_MAX_LEVERAGE", 3.0))
    market_timing_max_exposure_usd: float = field(default_factory=lambda: _env_float("MARKET_TIMING_MAX_EXPOSURE_USD", 500.0))
    market_timing_max_positions: int = field(default_factory=lambda: _env_int("MARKET_TIMING_MAX_POSITIONS", 5))


# Singleton – import this everywhere
settings = Settings()
