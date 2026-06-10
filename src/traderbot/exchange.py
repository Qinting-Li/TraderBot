import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any
from urllib.parse import urlencode

import aiohttp

from .config import Settings
from .models import ContractInfo, Side, TradeSignal

logger = logging.getLogger(__name__)


class Exchange:
    async def close(self) -> None:
        raise NotImplementedError

    async def account_equity(self) -> float:
        raise NotImplementedError

    async def contract_info(self, symbol: str) -> ContractInfo:
        raise NotImplementedError

    async def set_leverage(self, symbol: str, leverage: int) -> dict[str, Any]:
        raise NotImplementedError

    async def place_entry_order(self, signal: TradeSignal, size: float) -> dict[str, Any]:
        raise NotImplementedError

    async def place_stop_order(self, signal: TradeSignal, size: float, trigger_price: float) -> dict[str, Any]:
        raise NotImplementedError


class DryRunExchange(Exchange):
    def __init__(self, equity_usdt: float = 10_000.0):
        self.equity_usdt = equity_usdt

    async def close(self) -> None:
        return None

    async def account_equity(self) -> float:
        return self.equity_usdt

    async def contract_info(self, symbol: str) -> ContractInfo:
        return ContractInfo(
            symbol=symbol,
            min_size=0.001,
            max_size=1_000_000,
            size_multiplier=0.001,
            price_precision=2,
            size_precision=3,
            min_notional=5,
            status="normal",
        )

    async def set_leverage(self, symbol: str, leverage: int) -> dict[str, Any]:
        logger.info("DRY RUN set leverage %s %sx", symbol, leverage)
        return {"code": "00000", "dryRun": True}

    async def place_entry_order(self, signal: TradeSignal, size: float) -> dict[str, Any]:
        logger.info("DRY RUN entry %s %s size=%s entry=%s", signal.side.value, signal.symbol, size, signal.entry)
        return {"code": "00000", "dryRun": True, "data": {"orderId": f"dry-{int(time.time())}"}}

    async def place_stop_order(self, signal: TradeSignal, size: float, trigger_price: float) -> dict[str, Any]:
        logger.info("DRY RUN stop/target %s size=%s trigger=%s", signal.symbol, size, trigger_price)
        return {"code": "00000", "dryRun": True}


class BitgetExchange(Exchange):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        self._contracts: dict[str, ContractInfo] = {}

    async def close(self) -> None:
        await self.session.close()

    async def account_equity(self) -> float:
        data = await self._request(
            "GET",
            "/api/v2/mix/account/accounts",
            params={"productType": self.settings.product_type},
        )
        accounts = data.get("data") or []
        for account in accounts:
            if account.get("marginCoin") == self.settings.margin_coin:
                return float(account.get("available") or account.get("equity") or 0)
        raise RuntimeError("Unable to read Bitget account equity")

    async def contract_info(self, symbol: str) -> ContractInfo:
        if symbol in self._contracts:
            return self._contracts[symbol]
        data = await self._request(
            "GET",
            "/api/v2/mix/market/contracts",
            params={"productType": self.settings.product_type, "symbol": symbol},
        )
        rows = data.get("data") or []
        if not rows:
            raise RuntimeError(f"Unknown Bitget contract: {symbol}")
        row = rows[0]
        info = ContractInfo(
            symbol=row["symbol"],
            min_size=float(row.get("minTradeNum") or 0.001),
            max_size=float(row.get("maxTradeNum") or 1_000_000),
            size_multiplier=float(row.get("sizeMultiplier") or 0.001),
            price_precision=int(row.get("pricePlace") or 2),
            size_precision=int(row.get("volumePlace") or 3),
            min_notional=float(row.get("minTradeUSDT") or row.get("minOrderUSDT") or 5),
            status=row.get("symbolStatus", "normal"),
        )
        self._contracts[symbol] = info
        return info

    async def set_leverage(self, symbol: str, leverage: int) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/v2/mix/account/set-leverage",
            data={
                "symbol": symbol,
                "productType": self.settings.product_type,
                "marginCoin": self.settings.margin_coin,
                "leverage": str(leverage),
            },
        )

    async def place_entry_order(self, signal: TradeSignal, size: float) -> dict[str, Any]:
        side = "buy" if signal.side == Side.LONG else "sell"
        return await self._request(
            "POST",
            "/api/v2/mix/order/place-order",
            data={
                "symbol": signal.symbol,
                "productType": self.settings.product_type,
                "marginMode": self.settings.margin_mode,
                "marginCoin": self.settings.margin_coin,
                "size": str(size),
                "side": side,
                "tradeSide": "open",
                "orderType": "market",
                "clientOid": f"traderbot-{int(time.time() * 1000)}",
            },
        )

    async def place_stop_order(self, signal: TradeSignal, size: float, trigger_price: float) -> dict[str, Any]:
        side = "sell" if signal.side == Side.LONG else "buy"
        return await self._request(
            "POST",
            "/api/v2/mix/order/place-plan-order",
            data={
                "symbol": signal.symbol,
                "productType": self.settings.product_type,
                "marginMode": self.settings.margin_mode,
                "marginCoin": self.settings.margin_coin,
                "size": str(size),
                "side": side,
                "tradeSide": "close",
                "orderType": "market",
                "triggerPrice": str(trigger_price),
                "triggerType": "mark_price",
                "clientOid": f"traderbot-plan-{int(time.time() * 1000)}",
            },
        )

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        query = f"?{urlencode(params)}" if params else ""
        body = json.dumps(data, separators=(",", ":")) if data else ""
        request_path = path + query
        timestamp = str(int(time.time() * 1000))
        headers = self._headers(timestamp, method, request_path, body)
        async with self.session.request(
            method,
            self.settings.bitget_api_base + request_path,
            data=body if body else None,
            headers=headers,
        ) as response:
            payload = await response.json(content_type=None)
            if response.status >= 400 or payload.get("code") not in (None, "00000"):
                raise RuntimeError(f"Bitget API error {response.status}: {payload}")
            return payload

    def _headers(self, timestamp: str, method: str, request_path: str, body: str) -> dict[str, str]:
        message = f"{timestamp}{method.upper()}{request_path}{body}"
        signature = base64.b64encode(
            hmac.new(
                self.settings.bitget_secret_key.encode(),
                message.encode(),
                hashlib.sha256,
            ).digest()
        ).decode()
        return {
            "ACCESS-KEY": self.settings.bitget_api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.settings.bitget_passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }
