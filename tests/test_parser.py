from traderbot.models import MarketType, Side
from traderbot.parser import SignalParser


def test_parse_multiline_futures_signal():
    text = """
    BTCUSDT LONG
    Entry: 65000
    SL: 64000
    TP1: 66000
    TP2: 67500
    """

    signals = SignalParser().parse(text)

    assert len(signals) == 1
    signal = signals[0]
    assert signal.symbol == "BTCUSDT"
    assert signal.side == Side.LONG
    assert signal.entry == 65000
    assert signal.stop_loss == 64000
    assert signal.take_profits == [66000, 67500]
    assert signal.market_type == MarketType.FUTURES
    assert signal.confidence >= 0.65


def test_forced_spot_market_override():
    signals = SignalParser().parse("ETH short entry 3500 stop 3560 tp 3400", forced_market=MarketType.SPOT)

    assert len(signals) == 1
    assert signals[0].symbol == "ETHUSDT"
    assert signals[0].side == Side.SHORT
    assert signals[0].market_type == MarketType.SPOT


def test_parse_multiple_take_profit_values_on_one_line():
    signals = SignalParser().parse("ETH short entry 3500 stop 3560 take profit 3400 3300")

    assert len(signals) == 1
    assert signals[0].take_profits == [3300, 3400]
