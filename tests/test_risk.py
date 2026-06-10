from traderbot.models import ContractInfo, Side, TradeSignal
from traderbot.risk import RiskManager


def test_position_plan_uses_stop_distance_and_notional_cap():
    risk = RiskManager(risk_per_trade_percent=0.01, max_leverage=5, max_notional=500)
    contract = ContractInfo(
        symbol="BTCUSDT",
        min_size=0.001,
        max_size=100,
        size_multiplier=0.001,
        price_precision=2,
        size_precision=3,
        min_notional=5,
    )
    signal = TradeSignal(symbol="BTCUSDT", side=Side.LONG, entry=50_000, stop_loss=49_000)

    plan = risk.position_plan(signal, equity_usdt=10_000, contract=contract)

    assert plan.notional <= 500.01
    assert plan.size == 0.01
    assert plan.leverage == 1
