# TraderBot

TraderBot is a Discord-to-Bitget trading signal bot. It listens to selected Discord
channels, extracts futures trade signals, applies risk controls, and can submit
orders to Bitget. The default mode is **dry run**, so it will parse and log trades
without placing real orders.

> This project is automation software, not financial advice. Use live trading only
> after auditing the code, testing with small size, and accepting the exchange and
> market risks.

## What Changed

- No hardcoded secrets. Tokens and API keys are read from environment variables.
- Dry-run is enabled by default. Live trading requires an explicit opt-in.
- The code is split into focused modules: config, parser, risk, exchange client,
  executor, Discord gateway, and app entrypoint.
- Risk controls include per-trade risk, max leverage, max notional, min confidence,
  and a simple per-symbol cooldown.
- Signal parsing is covered by unit tests.
- The README, `.env.example`, `.gitignore`, and dependency files are ready for a
  public repository.

## Project Layout

```text
src/traderbot/
  app.py            # Runtime wiring
  config.py         # Environment based settings
  discord_client.py # Discord gateway + REST helpers
  exchange.py       # Bitget REST client and dry-run exchange
  executor.py       # Trade execution workflow and cooldown checks
  models.py         # Shared dataclasses
  parser.py         # Text signal parser
  risk.py           # Position sizing
tests/
  test_parser.py
  test_risk.py
```

`Quant BOT.py` remains as a compatibility launcher.

## Setup

1. Create a virtual environment.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies.

```powershell
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and fill in your settings.

```powershell
Copy-Item .env.example .env
```

4. Run in dry-run mode.

```powershell
$env:PYTHONPATH = "src"
python -m traderbot
```

## Configuration

Environment variables:

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `DISCORD_BOT_TOKEN` | yes | | Discord bot token. |
| `DISCORD_CHANNEL_IDS` | yes | | Comma-separated channel or thread IDs. |
| `BITGET_API_KEY` | live only | | Bitget API key. |
| `BITGET_SECRET_KEY` | live only | | Bitget secret key. |
| `BITGET_PASSPHRASE` | live only | | Bitget passphrase. |
| `TRADERBOT_LIVE_TRADING` | no | `false` | Must be `true` to place real orders. |
| `RISK_PER_TRADE_PERCENT` | no | `0.01` | Equity fraction risked per trade. |
| `MAX_LEVERAGE` | no | `5` | Max futures leverage. |
| `MAX_POSITION_NOTIONAL_USDT` | no | `500` | Notional cap per signal. |
| `MIN_SIGNAL_CONFIDENCE` | no | `0.65` | Parser confidence threshold. |
| `SYMBOL_COOLDOWN_SECONDS` | no | `300` | Cooldown per symbol after execution. |
| `LOG_LEVEL` | no | `INFO` | Python logging level. |

Optional channel market overrides:

```powershell
$env:CHANNEL_MARKET_OVERRIDES = '{"123456789":"futures","987654321":"spot"}'
```

Spot signals are parsed and logged, but skipped by the futures executor.

## Signal Examples

```text
BTCUSDT LONG
Entry: 65000
SL: 64000
TP1: 66000
TP2: 67500
```

```text
ETH short entry 3500 stop 3560 take profit 3400 3300
```

The parser looks for a symbol, direction, entry, stop loss, and one or more take
profit targets. Signals with low confidence are ignored.

## Live Trading

Live trading is intentionally gated:

```powershell
$env:TRADERBOT_LIVE_TRADING = "true"
$env:PYTHONPATH = "src"
python -m traderbot
```

Before enabling live mode:

- Use a restricted Bitget API key.
- Disable withdrawal permission.
- Start with small account equity and conservative caps.
- Monitor logs and exchange order history.

## Tests

```powershell
pytest
```

## Security Notes

- Never commit `.env`, API keys, Discord tokens, or log files containing private
  messages.
- The default `.gitignore` excludes runtime logs and local environment files.
- Treat Discord signal sources as untrusted input.
