import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw in (None, "") else float(raw)


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw in (None, "") else int(raw)


def _csv_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _load_dotenv_file(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    discord_bot_token: str
    discord_channel_ids: list[str]
    bitget_api_key: str = ""
    bitget_secret_key: str = ""
    bitget_passphrase: str = ""
    bitget_api_base: str = "https://api.bitget.com"
    live_trading: bool = False
    product_type: str = "USDT-FUTURES"
    margin_coin: str = "USDT"
    margin_mode: str = "isolated"
    risk_per_trade_percent: float = 0.01
    max_leverage: int = 5
    max_position_notional_usdt: float = 500.0
    min_signal_confidence: float = 0.65
    symbol_cooldown_seconds: int = 300
    channel_market_overrides: dict[str, str] = field(default_factory=dict)
    log_level: str = "INFO"

    @property
    def dry_run(self) -> bool:
        return not self.live_trading

    def validate(self) -> None:
        missing = []
        if not self.discord_bot_token:
            missing.append("DISCORD_BOT_TOKEN")
        if not self.discord_channel_ids:
            missing.append("DISCORD_CHANNEL_IDS")
        if missing:
            raise ValueError(f"Missing required settings: {', '.join(missing)}")

        if self.live_trading:
            live_missing = [
                name
                for name, value in {
                    "BITGET_API_KEY": self.bitget_api_key,
                    "BITGET_SECRET_KEY": self.bitget_secret_key,
                    "BITGET_PASSPHRASE": self.bitget_passphrase,
                }.items()
                if not value
            ]
            if live_missing:
                raise ValueError(
                    "Live trading requested but Bitget credentials are missing: "
                    + ", ".join(live_missing)
                )


def load_settings() -> Settings:
    _load_dotenv_file()
    overrides_raw = os.getenv("CHANNEL_MARKET_OVERRIDES", "").strip()
    overrides = json.loads(overrides_raw) if overrides_raw else {}
    settings = Settings(
        discord_bot_token=os.getenv("DISCORD_BOT_TOKEN", "").strip(),
        discord_channel_ids=_csv_env("DISCORD_CHANNEL_IDS"),
        bitget_api_key=os.getenv("BITGET_API_KEY", "").strip(),
        bitget_secret_key=os.getenv("BITGET_SECRET_KEY", "").strip(),
        bitget_passphrase=os.getenv("BITGET_PASSPHRASE", "").strip(),
        bitget_api_base=os.getenv("BITGET_API_BASE", "https://api.bitget.com").rstrip("/"),
        live_trading=_bool_env("TRADERBOT_LIVE_TRADING", False),
        product_type=os.getenv("BITGET_PRODUCT_TYPE", "USDT-FUTURES"),
        margin_coin=os.getenv("BITGET_MARGIN_COIN", "USDT"),
        margin_mode=os.getenv("BITGET_MARGIN_MODE", "isolated"),
        risk_per_trade_percent=_float_env("RISK_PER_TRADE_PERCENT", 0.01),
        max_leverage=_int_env("MAX_LEVERAGE", 5),
        max_position_notional_usdt=_float_env("MAX_POSITION_NOTIONAL_USDT", 500.0),
        min_signal_confidence=_float_env("MIN_SIGNAL_CONFIDENCE", 0.65),
        symbol_cooldown_seconds=_int_env("SYMBOL_COOLDOWN_SECONDS", 300),
        channel_market_overrides=overrides,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
    settings.validate()
    return settings
