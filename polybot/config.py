"""Centralised configuration loaded from env / .env file."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All tunables live here.  Extend freely – Pydantic validates on startup."""

    # ── Polymarket CLOB credentials ──────────────────────────────────────
    polymarket_api_key: str = ""
    polymarket_secret: str = ""
    polymarket_passphrase: str = ""
    private_key: str = ""

    # ── Chain / network ──────────────────────────────────────────────────
    chain_id: int = 137  # Polygon mainnet

    # ── Runtime behaviour ────────────────────────────────────────────────
    dry_run: bool = True
    log_level: str = "INFO"
    tick_interval_seconds: float = Field(default=10.0, description="Main loop cadence")

    # ── Risk limits (override per-strategy via strategy config) ─────────
    max_position_size_usd: float = 100.0
    max_open_orders: int = 10

    # ── Market-timing hedge strategy ─────────────────────────────────────
    market_timing_enabled: bool = True
    market_timing_lookback: int = Field(default=20, description="Ticks of price history for momentum calc")
    market_timing_ema_fast: int = 5
    market_timing_ema_slow: int = 15
    market_timing_momentum_threshold: float = Field(default=0.02, description="Min EMA spread to trigger directional entry")
    market_timing_hedge_ratio: float = Field(default=0.5, description="Fraction of position to hedge (0=none, 1=full)")
    market_timing_base_size_usd: float = 10.0
    market_timing_max_leverage: float = Field(default=3.0, description="Max multiplier on base size when conviction is high")
    market_timing_max_exposure_usd: float = Field(default=500.0, description="Hard cap on total strategy exposure")
    market_timing_max_positions: int = 5

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


# Singleton – import this everywhere
settings = Settings()
