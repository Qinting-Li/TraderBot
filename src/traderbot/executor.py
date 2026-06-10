import logging
import time

from .config import Settings
from .exchange import Exchange
from .models import ExecutionResult, MarketType, TradeSignal
from .risk import RiskManager

logger = logging.getLogger(__name__)


class TradeExecutor:
    def __init__(self, settings: Settings, exchange: Exchange, risk: RiskManager):
        self.settings = settings
        self.exchange = exchange
        self.risk = risk
        self._last_symbol_trade_at: dict[str, float] = {}

    async def execute(self, signal: TradeSignal) -> ExecutionResult:
        if signal.market_type == MarketType.SPOT:
            return ExecutionResult(False, self.settings.dry_run, "spot signals are skipped")
        if signal.confidence < self.settings.min_signal_confidence:
            return ExecutionResult(False, self.settings.dry_run, "signal confidence below threshold")
        if self._cooling_down(signal.symbol):
            return ExecutionResult(False, self.settings.dry_run, "symbol cooldown active")

        contract = await self.exchange.contract_info(signal.symbol)
        equity = await self.exchange.account_equity()
        plan = self.risk.position_plan(signal, equity, contract)

        await self.exchange.set_leverage(signal.symbol, plan.leverage)
        response = await self.exchange.place_entry_order(signal, plan.size)

        if signal.stop_loss:
            await self.exchange.place_stop_order(signal, plan.size, signal.stop_loss)

        for target in signal.take_profits:
            tp_size = round(plan.size / max(1, len(signal.take_profits)), contract.size_precision)
            await self.exchange.place_stop_order(signal, tp_size, target)

        self._last_symbol_trade_at[signal.symbol] = time.time()
        logger.info(
            "accepted signal symbol=%s side=%s size=%s notional=%.2f dry_run=%s",
            signal.symbol,
            signal.side.value,
            plan.size,
            plan.notional,
            self.settings.dry_run,
        )
        return ExecutionResult(True, self.settings.dry_run, "accepted", response)

    def _cooling_down(self, symbol: str) -> bool:
        last = self._last_symbol_trade_at.get(symbol)
        if last is None:
            return False
        return time.time() - last < self.settings.symbol_cooldown_seconds
