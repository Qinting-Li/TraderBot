import math

from .models import ContractInfo, PositionPlan, TradeSignal


class RiskManager:
    def __init__(self, risk_per_trade_percent: float, max_leverage: int, max_notional: float):
        if not 0 < risk_per_trade_percent <= 0.1:
            raise ValueError("risk_per_trade_percent must be between 0 and 0.1")
        self.risk_per_trade_percent = risk_per_trade_percent
        self.max_leverage = max_leverage
        self.max_notional = max_notional

    def position_plan(self, signal: TradeSignal, equity_usdt: float, contract: ContractInfo) -> PositionPlan:
        if equity_usdt <= 0:
            raise ValueError("equity_usdt must be positive")
        if signal.entry <= 0:
            raise ValueError("entry price must be positive")
        if not contract.is_tradable:
            raise ValueError(f"{contract.symbol} is not tradable")

        risk_amount = equity_usdt * self.risk_per_trade_percent
        if signal.stop_loss and signal.stop_loss > 0 and signal.stop_loss != signal.entry:
            per_unit_risk = abs(signal.entry - signal.stop_loss)
            raw_size = risk_amount / per_unit_risk
        else:
            raw_size = self.max_notional / signal.entry

        notional_cap = min(self.max_notional, equity_usdt * self.max_leverage)
        capped_size = min(raw_size, notional_cap / signal.entry)
        size = self._round_down(capped_size, contract.size_precision)

        if size < contract.min_size:
            size = contract.min_size
        if size > contract.max_size:
            size = contract.max_size

        notional = size * signal.entry
        if notional < contract.min_notional:
            size = self._round_up(contract.min_notional / signal.entry, contract.size_precision)
            notional = size * signal.entry

        if notional > notional_cap * 1.001:
            raise ValueError("position would exceed notional cap")

        leverage = min(self.max_leverage, max(1, math.ceil(notional / equity_usdt)))
        return PositionPlan(size=size, notional=notional, risk_amount=risk_amount, leverage=leverage)

    def _round_down(self, value: float, precision: int) -> float:
        factor = 10**precision
        return math.floor(value * factor) / factor

    def _round_up(self, value: float, precision: int) -> float:
        factor = 10**precision
        return math.ceil(value * factor) / factor
