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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


# Singleton – import this everywhere
settings = Settings()
