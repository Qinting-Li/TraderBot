import re

from .models import MarketType, Side, TradeSignal


COMMON_SYMBOLS = {
    "BTC": "BTCUSDT",
    "BITCOIN": "BTCUSDT",
    "ETH": "ETHUSDT",
    "ETHEREUM": "ETHUSDT",
    "SOL": "SOLUSDT",
    "BNB": "BNBUSDT",
    "XRP": "XRPUSDT",
    "ADA": "ADAUSDT",
    "DOGE": "DOGEUSDT",
    "LINK": "LINKUSDT",
    "AVAX": "AVAXUSDT",
    "DOT": "DOTUSDT",
    "MATIC": "MATICUSDT",
}

SYMBOL_RE = re.compile(r"\b([A-Z0-9]{2,20})(?:[-_/ ]?USDT|/USDT|USDT)?\b", re.I)
NUMBER_RE = re.compile(r"(?<![A-Za-z])([0-9]+(?:\.[0-9]+)?)")


class SignalParser:
    """Extracts simple futures signals from Discord text."""

    side_patterns = {
        Side.LONG: re.compile(r"\b(long|buy|bull|多|做多|看多)\b", re.I),
        Side.SHORT: re.compile(r"\b(short|sell|bear|空|做空|看空)\b", re.I),
    }

    entry_re = re.compile(r"(?:entry|entries|enter|入场|进场|开仓|price|限价)\D*([0-9]+(?:\.[0-9]+)?)", re.I)
    stop_re = re.compile(r"(?:sl|stop|stoploss|stop loss|止损)\D*([0-9]+(?:\.[0-9]+)?)", re.I)
    tp_re = re.compile(r"(?:tp\d*|take profit|target|止盈|目标)\D*([0-9]+(?:\.[0-9]+)?)", re.I)

    def parse(self, text: str, forced_market: MarketType | None = None) -> list[TradeSignal]:
        cleaned = self._normalize(text)
        chunks = self._split_candidate_chunks(cleaned)
        signals: list[TradeSignal] = []
        for chunk in chunks:
            signal = self._parse_chunk(chunk, forced_market)
            if signal:
                signals.append(signal)
        return self._dedupe(signals)

    def _parse_chunk(self, chunk: str, forced_market: MarketType | None) -> TradeSignal | None:
        side = self._find_side(chunk)
        symbol = self._find_symbol(chunk)
        entry = self._find_entry(chunk)
        if not side or not symbol or entry is None:
            return None

        stop_loss = self._find_one(self.stop_re, chunk)
        take_profits = self._find_take_profits(chunk)
        market_type = forced_market or self._find_market_type(chunk)
        confidence = self._confidence(symbol, side, entry, stop_loss, take_profits, chunk)

        return TradeSignal(
            symbol=symbol,
            side=side,
            entry=entry,
            stop_loss=stop_loss,
            take_profits=take_profits,
            market_type=market_type,
            confidence=confidence,
            source=chunk[:500],
        )

    def _normalize(self, text: str) -> str:
        text = text.replace("：", ":").replace("，", ",").replace("、", ",")
        text = re.sub(r"[ \t]+", " ", text)
        return text.strip()

    def _split_candidate_chunks(self, text: str) -> list[str]:
        blocks = [block.strip() for block in re.split(r"\n{2,}|-{3,}", text) if block.strip()]
        return blocks or [text]

    def _find_side(self, text: str) -> Side | None:
        for side, pattern in self.side_patterns.items():
            if pattern.search(text):
                return side
        return None

    def _find_symbol(self, text: str) -> str | None:
        upper = text.upper()
        for alias, symbol in COMMON_SYMBOLS.items():
            if re.search(rf"\b{re.escape(alias)}\b", upper):
                return symbol
        for match in SYMBOL_RE.finditer(upper):
            token = match.group(1)
            if token in {"LONG", "SHORT", "SELL", "BUY", "ENTRY", "STOP", "TARGET", "USDT"}:
                continue
            if token.endswith("USDT"):
                return token
            return f"{token}USDT"
        return None

    def _find_entry(self, text: str) -> float | None:
        direct = self._find_one(self.entry_re, text)
        if direct is not None:
            return direct
        numbers = [float(value) for value in NUMBER_RE.findall(text)]
        return numbers[0] if numbers else None

    def _find_one(self, pattern: re.Pattern[str], text: str) -> float | None:
        match = pattern.search(text)
        return float(match.group(1)) if match else None

    def _find_take_profits(self, text: str) -> list[float]:
        values = [float(match.group(1)) for match in self.tp_re.finditer(text)]
        for line in text.splitlines():
            marker = re.search(r"\b(?:tp\d*|take profit|target)\b|止盈|目标", line, re.I)
            if marker:
                values.extend(float(value) for value in NUMBER_RE.findall(line[marker.end() :]))
        return sorted(set(values))

    def _find_market_type(self, text: str) -> MarketType:
        lower = text.lower()
        if "spot" in lower or "现货" in text:
            return MarketType.SPOT
        return MarketType.FUTURES

    def _confidence(
        self,
        symbol: str,
        side: Side,
        entry: float,
        stop_loss: float | None,
        take_profits: list[float],
        text: str,
    ) -> float:
        score = 0.35
        score += 0.15 if symbol else 0
        score += 0.15 if side else 0
        score += 0.15 if entry > 0 else 0
        score += 0.12 if stop_loss else 0
        score += 0.08 if take_profits else 0
        if len(text) < 20:
            score -= 0.15
        return max(0.0, min(score, 1.0))

    def _dedupe(self, signals: list[TradeSignal]) -> list[TradeSignal]:
        seen: set[tuple[str, str, float]] = set()
        unique: list[TradeSignal] = []
        for signal in sorted(signals, key=lambda item: item.confidence, reverse=True):
            key = (signal.symbol, signal.side.value, signal.entry)
            if key in seen:
                continue
            seen.add(key)
            unique.append(signal)
        return unique
