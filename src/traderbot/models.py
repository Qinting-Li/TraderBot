from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class MarketType(str, Enum):
    FUTURES = "futures"
    SPOT = "spot"


@dataclass(frozen=True)
class TradeSignal:
    symbol: str
    side: Side
    entry: float
    stop_loss: float | None = None
    take_profits: list[float] = field(default_factory=list)
    market_type: MarketType = MarketType.FUTURES
    confidence: float = 0.0
    source: str = ""


@dataclass(frozen=True)
class ContractInfo:
    symbol: str
    min_size: float
    max_size: float
    size_multiplier: float
    price_precision: int
    size_precision: int
    min_notional: float
    status: str = "normal"

    @property
    def is_tradable(self) -> bool:
        return self.status.lower() == "normal"


@dataclass(frozen=True)
class PositionPlan:
    size: float
    notional: float
    risk_amount: float
    leverage: int
    reason: str = ""


@dataclass(frozen=True)
class ExecutionResult:
    accepted: bool
    dry_run: bool
    reason: str
    exchange_response: dict[str, Any] | None = None
