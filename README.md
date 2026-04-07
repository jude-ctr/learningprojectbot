# Polybot – Polymarket Trading Bot Skeleton

Extensible skeleton for building automated trading strategies on [Polymarket](https://polymarket.com).

## Architecture

```
cli.py          → entry-point, wires everything together
engine.py       → main tick loop: data → strategy → risk → execution
connectors/     → exchange adapters (Polymarket CLOB)
strategies/     → plug-in strategies (inherit BaseStrategy)
risk/           → pre-trade risk checks
utils/          → logging, helpers
```

## Quick start

```bash
cp .env.example .env          # fill in your keys
pip install -e ".[dev]"
python -m polybot.cli          # or: polybot
```

Starts in **dry-run mode** by default (`DRY_RUN=true`).

## Adding a strategy

1. Create a file in `polybot/strategies/`.
2. Subclass `BaseStrategy` and implement `on_tick`.
3. Register it in `cli.py`.

## Running tests

```bash
pytest
```
