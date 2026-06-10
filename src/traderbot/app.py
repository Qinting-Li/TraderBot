import asyncio
import logging

from .config import Settings, load_settings
from .discord_client import DiscordGatewayClient
from .exchange import BitgetExchange, DryRunExchange, Exchange
from .executor import TradeExecutor
from .models import MarketType
from .parser import SignalParser
from .risk import RiskManager


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler("traderbot.log", encoding="utf-8")],
    )


async def main() -> None:
    settings = load_settings()
    configure_logging(settings)
    logger = logging.getLogger(__name__)
    parser = SignalParser()
    risk = RiskManager(
        settings.risk_per_trade_percent,
        settings.max_leverage,
        settings.max_position_notional_usdt,
    )
    exchange: Exchange = DryRunExchange() if settings.dry_run else BitgetExchange(settings)
    executor = TradeExecutor(settings, exchange, risk)

    async def handle_message(text: str, forced_market: MarketType | None) -> None:
        signals = parser.parse(text, forced_market=forced_market)
        if not signals:
            logger.debug("message ignored: no signal")
            return
        for signal in signals:
            try:
                result = await executor.execute(signal)
                logger.info("signal result accepted=%s reason=%s", result.accepted, result.reason)
            except Exception:
                logger.exception("failed to process signal")

    client = DiscordGatewayClient(
        settings.discord_bot_token,
        settings.discord_channel_ids,
        settings.channel_market_overrides,
        handle_message,
    )
    logger.info("starting TraderBot dry_run=%s channels=%s", settings.dry_run, len(settings.discord_channel_ids))
    try:
        await client.start()
    finally:
        await client.stop()
        await exchange.close()


def run() -> None:
    asyncio.run(main())
