# -*- coding: utf-8 -*-
"""
Discord + Bitget 自动化交易系统 

本版变更：
- “代码常量”配置 Token/Key
- 功能：引用补全、启动回溯、更全面文本提取、时间同步、三态市场判定、三态统计、
  风控与Bitget v2真实下单、止盈止损计划单等。
"""

import os
import json
import asyncio
import logging
import re
import hashlib
import hmac
import base64
import time
from dataclasses import dataclass
from typing import Dict, Optional, Any, List, Tuple, Set
from datetime import datetime
from pathlib import Path
import aiohttp
from urllib.parse import urlencode

# =========================
# ====== 【配置区】 ========
# =========================

# 直接在此处填入你的 Discord Bot Token（不要留空）
DISCORD_BOT_TOKEN = "真实的TOKEN"  

# 目标频道/父论坛/线程 ID（可多个）
DISCORD_CHANNEL_IDS = [
    "1",
    "2",
    "3",
]

# 可选：按频道设置默认市场类型（"futures" 或 "spot"）
CHANNEL_DEFAULT_MARKET = {
    "1401165613572952124": "futures",
    "1401166240244039741": "futures",
    # "某现货频道ID": "spot",
}
FORCE_MARKET_OVERRIDE = True  # True 时启用按频道默认市场强制覆盖

# ====== Bitget API配置  ======
BITGET_API_BASE = "https://api.bitget.com"
BITGET_API_KEY = " - "                  
BITGET_SECRET_KEY = " - "            
BITGET_PASSPHRASE = " - "        

# 交易策略配置
RISK_PER_TRADE_PERCENT = 0.01
MAX_LEVERAGE = 5
DEFAULT_SYMBOL = "BTCUSDT"

# v2 标准参数
PRODUCT_TYPE = "USDT-FUTURES"
MARGIN_COIN = "USDT"
MARGIN_MODE = "isolated"

# ====== Discord 网关/REST 基本配置 ======
DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"

# Discord Intents配置（必须在开发者后台开启 Message Content）
INTENT_GUILDS = 1 << 0
INTENT_GUILD_MESSAGES = 1 << 9
INTENT_DIRECT_MESSAGES = 1 << 12
INTENT_MESSAGE_CONTENT = 1 << 15
DISCORD_INTENTS = INTENT_GUILDS | INTENT_GUILD_MESSAGES | INTENT_DIRECT_MESSAGES | INTENT_MESSAGE_CONTENT

# ====== 日志配置 ======
LOG_DIR = Path("logs/messages")
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("trading_bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("trading_bot")

# ====== 小工具：占位符检测与掩码 ======
def _is_placeholder(s: Optional[str]) -> bool:
    return not s or s.strip() == "" or s.strip().upper().startswith("YOUR_") or s.strip().upper().startswith("PUT_")

def _mask(s: str, left: int = 4, right: int = 3) -> str:
    if not s:
        return "EMPTY"
    if len(s) <= left + right:
        return "*" * len(s)
    return f"{s[:left]}***{s[-right:]}"

# ====== 合约信息数据结构 ======
@dataclass
class ContractInfo:
    symbol: str
    base_coin: str
    quote_coin: str
    min_trade_num: float
    max_trade_num: float
    size_multiplier: float
    price_precision: int
    size_precision: int
    min_order_usd: float
    status: str  # v2字段symbolStatus: normal/maintain/offline

    @property
    def is_tradable(self) -> bool:
        return self.status == "normal"

# ====== 符号映射/提示 ======
COMMON_SYMBOLS = {
    # 主流
    "BTC": "BTCUSDT", "BITCOIN": "BTCUSDT", "BTCUSDT": "BTCUSDT", "BTC-PERP": "BTCUSDT",
    "ETH": "ETHUSDT", "ETHEREUM": "ETHUSDT", "ETHUSDT": "ETHUSDT", "ETH-PERP": "ETHUSDT",
    "SOL": "SOLUSDT", "SOLANA": "SOLUSDT", "SOLUSDT": "SOLUSDT",
    "BNB": "BNBUSDT", "BNBUSDT": "BNBUSDT",
    "XRP": "XRPUSDT", "RIPPLE": "XRPUSDT", "XRPUSDT": "XRPUSDT",
    "ADA": "ADAUSDT", "CARDANO": "ADAUSDT", "ADAUSDT": "ADAUSDT",
    "AVAX": "AVAXUSDT", "AVALANCHE": "AVAXUSDT", "AVAXUSDT": "AVAXUSDT",
    "DOT": "DOTUSDT", "POLKADOT": "DOTUSDT", "DOTUSDT": "DOTUSDT",
    "LINK": "LINKUSDT", "CHAINLINK": "LINKUSDT", "LINKUSDT": "LINKUSDT",
    "MATIC": "MATICUSDT", "POLYGON": "MATICUSDT", "MATICUSDT": "MATICUSDT",

    # DeFi/L1
    "INJ": "INJUSDT", "INJECTIVE": "INJUSDT", "INJUSDT": "INJUSDT",
    "CRV": "CRVUSDT", "CURVE": "CRVUSDT", "CRVUSDT": "CRVUSDT",
    "SEI": "SEIUSDT", "SEIUSDT": "SEIUSDT",
    "TAO": "TAOUSDT", "BITTENSOR": "TAOUSDT", "TAOUSDT": "TAOUSDT",
    "ENA": "ENAUSDT", "ETHENA": "ENAUSDT", "ENAUSDT": "ENAUSDT",

    # 热门/梗
    "DOGE": "DOGEUSDT", "DOGECOIN": "DOGEUSDT", "DOGEUSDT": "DOGEUSDT",
    "SHIB": "SHIBUSDT", "SHIBUSDT": "SHIBUSDT",
    "PEPE": "PEPEUSDT", "PEPEUSDT": "PEPEUSDT",
    "WIF": "WIFUSDT", "WIFUSDT": "WIFUSDT",
    "BONK": "BONKUSDT", "BONKUSDT": "BONKUSDT",
    "MOG": "MOGUSDT", "MOGUSDT": "MOGUSDT",
    "HYPE": "HYPEUSDT", "HYPEUSDT": "HYPEUSDT",

    # 样例项目 / 新币别名（可按需增补）
    "MAGIC": "MAGICUSDT", "MAGICUSDT": "MAGICUSDT",
    "PROVE": "PROVEUSDT", "PROVEUSDT": "PROVEUSDT",
    "SIREN": "SIRENUSDT", "SIRENUSDT": "SIRENUSDT",
    "ZORA": "ZORAUSDT", "ZORAUSDT": "ZORAUSDT",
    "A2Z": "A2ZUSDT", "A2ZUSDT": "A2ZUSDT",
    "USELESS": "USELESSUSDT", "USELESSUSDT": "USELESSUSDT",
    "PUMPFUN": "PUMPFUNUSDT", "PUMPFUNUSDT": "PUMPFUNUSDT",
    "FARTCOIN": "FARTCOINUSDT", "FARTCOINUSDT": "FARTCOINUSDT",
    "WASDER": "WASDERUSDT", "WASDERUSDT": "WASDERUSDT",
    "KOMPETE": "KOMPETEUSDT", "KOMPETEUSDT": "KOMPETEUSDT",
    "ESPORTS": "ESPORTSUSDT", "ESPORTSUSDT": "ESPORTSUSDT",
}

SPOT_HINTS = [
    "@✍active-现货", "@✍active-Spot", "@✍active-spot", "@✍active-现貨",
    "现货", "現貨", "spot", "现货做多", "現貨做多"
]
FUTURES_HINTS = ["@🧲active-futures", "@active-futures", "@active-future", "合约", "永续", "futures"]

HEADING_HINTS = [
    "限价订单", "尚未成交", "有效订单", "可入场", "已入场订单",
    "触发订单", "Triggered Orders", "Active Orders", "Limit Orders",
    "Signal Reminder", "信号提醒", "策略警报", "Strategy Alert",
    "发送时间", "轉發", "已轉發", "已转发", "观察者聚合", "應用", "应用"
]

# ====== Bitget API 客户端 (带时间同步) ======
class BitgetAPIClient:
    def __init__(self, api_key: str, secret_key: str, passphrase: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.base_url = BITGET_API_BASE
        self.session: Optional[aiohttp.ClientSession] = None
        self._contract_cache: Dict[str, ContractInfo] = {}
        self._cache_timestamp = 0
        self._cache_ttl = 300
        self._time_offset_ms = 0
        logger.info("🔧 初始化Bitget API客户端")
        logger.info(f"   API Key: {_mask(api_key)}")

    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=60, connect=30, sock_read=30)
        self.session = aiohttp.ClientSession(timeout=timeout)
        await self._sync_time()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def _get_server_time_candidates(self) -> Optional[int]:
        endpoints = [
            "/api/v2/public/time",
            "/api/spot/v1/public/time",
            "/api/mix/v1/market/time",
        ]
        for ep in endpoints:
            try:
                async with self.session.get(self.base_url + ep) as resp:
                    txt = await resp.text()
                    data = json.loads(txt)
                    if isinstance(data.get("data"), dict) and "serverTime" in data["data"]:
                        return int(data["data"]["serverTime"])
                    if isinstance(data.get("data"), (int, str)):
                        return int(data["data"])
                    if "requestTime" in data:
                        return int(data["requestTime"])
            except Exception:
                continue
        return None

    async def _sync_time(self):
        server_ms = await self._get_server_time_candidates()
        if server_ms:
            local_ms = int(time.time() * 1000)
            self._time_offset_ms = server_ms - local_ms
            logger.info(f"⏱️ Bitget 时间同步完成：偏移 {self._time_offset_ms} ms")
        else:
            logger.warning("⚠️ 无法获取 Bitget 服务器时间，可能出现 40008 风险")

    def _generate_signature(self, timestamp_ms: str, method: str, request_path_with_query: str, body: str = "") -> str:
        message = f"{timestamp_ms}{method.upper()}{request_path_with_query}{body}"
        digest = hmac.new(self.secret_key.encode(), message.encode(), hashlib.sha256).digest()
        return base64.b64encode(digest).decode()

    def _headers(self, method: str, request_path_with_query: str, body: str = "") -> Dict[str, str]:
        timestamp_ms = str(int(time.time() * 1000 + self._time_offset_ms))
        signature = self._generate_signature(timestamp_ms, method, request_path_with_query, body)
        return {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp_ms,
            "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
            "X-CHANNEL-API-CODE": "python"
        }

    async def _request(self, method: str, path: str, params: Optional[Dict] = None, data: Optional[Dict] = None) -> Dict[str, Any]:
        query = "?" + urlencode(params, doseq=True) if params else ""
        url = self.base_url + path + query
        body = json.dumps(data, separators=(",", ":")) if data else ""
        headers = self._headers(method, path + query, body)

        async def do_once():
            async with self.session.request(method=method, url=url, headers=headers, data=body or None) as resp:
                text = await resp.text()
                try:
                    result = json.loads(text)
                except json.JSONDecodeError:
                    result = {"code": "error", "msg": f"Non-JSON response: {text}", "data": None}
                if resp.status != 200:
                    return {"http_status": resp.status, **result}
                return result

        result = await do_once()

        if (isinstance(result, dict) and
            (result.get("http_status") == 400 or result.get("code") in ("error",)) and
            ("timestamp" in json.dumps(result).lower() or "40008" in json.dumps(result))):
            logger.warning("⏳ 检测到时间相关错误，尝试同步服务器时间并重试...")
            await self._sync_time()
            headers = self._headers(method, path + query, body)
            result = await do_once()

        if isinstance(result, dict) and result.get("http_status"):
            logger.error(f"❌ API请求失败: {method} {path} -> HTTP {result.get('http_status')}")
            return {"code": "error", "msg": f"HTTP {result.get('http_status')}", "data": result}
        return result

    # === 支持 symbol 精确查询 ===
    async def get_contracts(self, product_type: str = PRODUCT_TYPE, symbol: Optional[str] = None) -> Dict[str, Any]:
        params = {"productType": product_type}
        if symbol:
            params["symbol"] = symbol
        return await self._request("GET", "/api/v2/mix/market/contracts", params=params)

    async def get_contract_info(self, symbol: str) -> Optional[ContractInfo]:
        current_time = time.time()
        need_refresh = (current_time - self._cache_timestamp > self._cache_ttl)
        # 缓存过期或无该symbol时，单币种直查一次
        if need_refresh or symbol not in self._contract_cache:
            try:
                res = await self.get_contracts(symbol=symbol)
                if res.get("code") == "00000":
                    items = res.get("data") or []
                    if items:
                        c = items[0]
                        info = ContractInfo(
                            symbol=c.get("symbol", symbol),
                            base_coin=c.get("baseCoin", ""),
                            quote_coin=c.get("quoteCoin", ""),
                            min_trade_num=float(c.get("minTradeNum", 0) or 0),
                            max_trade_num=float(c.get("maxTradeNum", 0) or 0),
                            size_multiplier=float(c.get("sizeMultiplier", 1) or 1),
                            price_precision=int(c.get("pricePlace", 2) or 2),
                            size_precision=int(c.get("volumePlace", 4) or 4),
                            min_order_usd=float(c.get("minTradeUSDT") or c.get("minOrderUSDT") or 5),
                            status=(c.get("symbolStatus") or c.get("status") or "offline"),
                        )
                        self._contract_cache[symbol] = info
                        self._cache_timestamp = time.time()
            except Exception as e:
                logger.warning(f"⚠️ 单币种合约信息直查失败 {symbol}: {e}")

        return self._contract_cache.get(symbol)

    async def _refresh_contract_cache(self):
        try:
            result = await self.get_contracts()
            if result.get("code") == "00000":
                contracts_data = result.get("data", [])
                self._contract_cache.clear()
                for c in contracts_data:
                    symbol = c.get("symbol")
                    if not symbol:
                        continue
                    info = ContractInfo(
                        symbol=symbol,
                        base_coin=c.get("baseCoin", ""),
                        quote_coin=c.get("quoteCoin", ""),
                        min_trade_num=float(c.get("minTradeNum", 0) or 0),
                        max_trade_num=float(c.get("maxTradeNum", 0) or 0),
                        size_multiplier=float(c.get("sizeMultiplier", 1) or 1),
                        price_precision=int(c.get("pricePlace", 2) or 2),
                        size_precision=int(c.get("volumePlace", 4) or 4),
                        # ✅ v2 正确字段
                        min_order_usd=float(c.get("minTradeUSDT") or c.get("minOrderUSDT") or 5),
                        # ✅ v2 正确字段
                        status=(c.get("symbolStatus") or c.get("status") or "offline"),
                    )
                    self._contract_cache[symbol] = info
                self._cache_timestamp = time.time()
                logger.info(f"✅ 合约信息缓存已更新，共 {len(self._contract_cache)} 个合约")
            else:
                logger.error(f"❌ 获取合约信息失败: {result}")
        except Exception as e:
            logger.error(f"❌ 刷新合约缓存异常: {e}")

    def format_price(self, price: float, symbol: str) -> str:
        ct = self._contract_cache.get(symbol)
        precision = ct.price_precision if ct else 4
        return f"{price:.{precision}f}"

    def format_size(self, size: float, symbol: str) -> str:
        ct = self._contract_cache.get(symbol)
        if ct:
            precision = ct.size_precision
            val = round(size, precision)
            if val < ct.min_trade_num:
                val = ct.min_trade_num
            return f"{val:.{precision}f}"
        return f"{size:.4f}"

    async def validate_symbol(self, symbol: str) -> bool:
        ct = await self.get_contract_info(symbol)
        if not ct:
            logger.warning(f"⚠️ 交易对不存在于 {PRODUCT_TYPE}: {symbol}")
            return False
        if not ct.is_tradable:
            logger.warning(f"⚠️ 交易对不可交易: {symbol} (状态: {ct.status})")
            return False
        return True

    async def get_account_info(self, v2_symbol: str) -> Dict[str, Any]:
        params = {"symbol": v2_symbol, "productType": PRODUCT_TYPE, "marginCoin": MARGIN_COIN}
        return await self._request("GET", "/api/v2/mix/account/account", params=params)

    async def set_leverage(self, v2_symbol: str, leverage: int) -> Dict[str, Any]:
        data = {
            "symbol": v2_symbol,
            "productType": PRODUCT_TYPE,
            "marginCoin": MARGIN_COIN,
            "leverage": str(leverage),
            "marginMode": MARGIN_MODE
        }
        return await self._request("POST", "/api/v2/mix/account/set-leverage", data=data)

    async def place_order(self, v2_symbol: str, side: str, trade_side: str, order_type: str,
                          size: str, price: Optional[str] = None, client_oid: Optional[str] = None) -> Dict[str, Any]:
        data = {
            "symbol": v2_symbol,
            "productType": PRODUCT_TYPE,
            "marginMode": MARGIN_MODE,
            "marginCoin": MARGIN_COIN,
            "side": side,
            "tradeSide": trade_side,
            "orderType": order_type,
            "size": size,
            "timeInForceValue": "normal"
        }
        if price and order_type == "limit":
            data["price"] = price
        if client_oid:
            data["clientOid"] = client_oid
        return await self._request("POST", "/api/v2/mix/order/place-order", data=data)

    async def place_stop_plan_order(self, v2_symbol: str, side: str, trigger_price: str,
                                    size: str, order_type: str = "market", trigger_type: str = "mark_price") -> Dict[str, Any]:
        data = {
            "planType": "normal_plan",
            "symbol": v2_symbol,
            "productType": PRODUCT_TYPE,
            "marginMode": MARGIN_MODE,
            "marginCoin": MARGIN_COIN,
            "size": size,
            "orderType": order_type,
            "triggerPrice": str(trigger_price),
            "triggerType": trigger_type,
            "side": side,
            "tradeSide": "close",
            "timeInForceValue": "normal"
        }
        return await self._request("POST", "/api/v2/mix/order/place-plan-order", data=data)

# ====== 解析数据结构 ======
@dataclass
class ParsedSignal:
    side: str             # LONG/SHORT
    symbol: str           # e.g., BTCUSDT
    entry: float          # 入场价格
    stop: Optional[float] # 止损价格
    is_spot: bool         # 是否现货
    take_profits: List[float]  # 止盈价格列表
    raw_line: str         # 原始命中行
    confidence: float     # 解析置信度 (0.0-1.0)s
    def __post_init__(self):
        if self.entry <= 0:
            raise ValueError("入场价格必须大于0")
        if self.stop and self.stop > 0:
            if self.side == "LONG" and self.stop >= self.entry:
                logger.warning(f"多单止损({self.stop})>=入场({self.entry})，自动修正为入场下方2%")
                self.stop = self.entry * 0.98
            elif self.side == "SHORT" and self.stop <= self.entry:
                logger.warning(f"空单止损({self.stop})<=入场({self.entry})，自动修正为入场上方2%")
                self.stop = self.entry * 1.02

# ====== 工具：符号归一化 ======
def normalize_symbol_from_text(text: str) -> Optional[str]:
    t = (text or "").upper()
    m = re.findall(r"\b([A-Z0-9]{2,20})USDT\b", t)
    for base in m:
        return base + "USDT"
    m2 = re.findall(r"\b([A-Z0-9]{2,20})-PERP\b", t)
    if m2:
        base = m2[0]
        return COMMON_SYMBOLS.get(base, base + "USDT")
    for k in sorted(COMMON_SYMBOLS.keys(), key=len, reverse=True):
        if re.search(fr"\b{re.escape(k)}\b", t):
            return COMMON_SYMBOLS[k]
    tokens = re.findall(r"\b([A-Z0-9]{2,20})\b", t)
    for tok in tokens:
        if tok in ["USD", "USDT", "BUSD", "USDC", "DAI", "LONG", "SHORT",
                   "STOP", "LOSS", "TAKE", "PROFIT", "ENTRY", "PRICE"]:
            continue
        return tok + "USDT"
    return None

# ====== 增强的多信号解析器 ======
class EnhancedMultiSignalParser:
    def __init__(self):
        self.long_keywords = ["long", "多", "做多", "买入", "開多", "开多", "看涨", "bullish", "buy", "call", "上涨"]
        self.short_keywords = ["short", "空", "做空", "卖出", "開空", "开空", "看跌", "bearish", "sell", "put", "下跌"]

        self.entry_keywords = ["entry", "opening", "开仓价", "開倉價", "入场", "入場", "进场", "進場", "价格", "price", "at", "@", "entry price"]
        self.stop_keywords  = ["stop", "loss", "sl", "止损", "止損", "停损", "停損", "stoploss", "止损价", "止損價"]
        self.tp_keywords    = ["take", "profit", "tp", "止盈", "獲利", "获利", "目标", "目標", "target"]

        entry_pat = r'(?:' + '|'.join(self.entry_keywords) + r')(?:\s+price)?[:：\s]*'
        stop_pat  = r'(?:' + '|'.join(self.stop_keywords)  + r')(?:\s+loss)?[:：\s]*'
        tp_pat    = r'(?:' + '|'.join(self.tp_keywords)    + r')(?:\s+profit)?[:：\s]*'
        bullet    = r'(?:^[\s]*[•\-\*\u2022]?\s*)'

        pat_en = re.compile(
            bullet +
            r'(?P<side>' + '|'.join(self.long_keywords + self.short_keywords) + r')\s+' +
            r'(?P<symbol>[A-Z0-9]{2,20}(?:USDT|usdt)?(?:-PERP)?)\s+' +
            entry_pat + r'(?P<entry>[\d.,\-\s/\(\)AVGavg:]+?)' +
            r'(?:\s+' + stop_pat + r'(?P<stop>(?:entry\s*price|入场价|入場價|建仓价|開倉價|开仓价|[0-9.,\-\s/\(\)]+)))?' +
            r'(?:\s+' + tp_pat   + r'(?P<tp>[\d.,\s/]+))?' +
            r'\s*$', re.IGNORECASE
        )

        pat_zh = re.compile(
            bullet +
            r'(?P<prefix_symbol>[A-Z0-9]{2,20}(?:USDT|usdt)?(?:-PERP)?)?\s*'
            r'(?P<side>多|空|看多|看空|long|short)\s*'
            r'(?:开仓价|開倉價|入场|入場|进场|進場|价格|價格|price)[:：\s]*'
            r'(?P<entry>[\d.,\-\s/\(\)AVGavg:]+?)'
            r'(?:\s*(?:止损|止損|停损|停損|stop\s*loss|sl|止损价|止損價)[:：\s]*(?P<stop>(?:入场价|入場價|建仓价|開倉價|开仓价|entry\s*price|[0-9.,\-\s/\(\)]+)))?'
            r'(?:\s*(?:止盈|獲利|获利|目标|目標|take\s*profit|tp)[:：\s]*(?P<tp>[\d.,\s/]+))?'
            r'\s*$', re.IGNORECASE
        )

        pat_en_alt = re.compile(
            bullet +
            r'(?P<symbol>[A-Z0-9]{2,20}(?:USDT|usdt)?(?:-PERP)?)\s+'
            r'(?P<side>' + '|'.join(self.long_keywords + self.short_keywords) + r')\s+'
            + entry_pat + r'(?P<entry>[\d.,\-\s/\(\)AVGavg:]+?)'
            r'(?:\s+' + stop_pat + r'(?P<stop>(?:entry\s*price|入场价|入場價|建仓价|開倉價|开仓价|[0-9.,\-\s/\(\)]+)))?'
            r'(?:\s+' + tp_pat   + r'(?P<tp>[\d.,\s/]+))?'
            r'\s*$', re.IGNORECASE
        )

        pat_table = re.compile(
            bullet +
            r'(?P<symbol>[A-Z0-9]{2,20}(?:USDT|usdt)?(?:-PERP)?)\s*\|\s*'
            r'(?P<side>' + '|'.join(self.long_keywords + self.short_keywords) + r')\s*\|\s*'
            r'(?P<entry>[\d.,\-\s/\(\)AVGavg:]+)\s*$',
            re.IGNORECASE
        )

        pat_price_only = re.compile(
            bullet +
            r'(?P<maybe_symbol>[A-Z0-9]{2,20}(?:USDT|usdt)?(?:-PERP)?)?\s*'
            r'(?:开仓价|開倉價|入场|入場|进场|進場|价格|價格|price)[:：\s]*'
            r'(?P<entry>[\d.,\-\s/\(\)AVGavg:]+)'
            r'(?:\s*(?:止损|止損|停损|停損|stop\s*loss|sl|止损价|止損價)[:：\s]*(?P<stop>(?:入场价|入場價|建仓价|開倉價|开仓价|entry\s*price|[0-9.,\-\s/\(\)]+)))?'
            r'(?:\s*(?:止盈|獲利|获利|目标|目標|take\s*profit|tp)[:：\s]*(?P<tp>[\d.,\s/]+))?\s*$',
            re.IGNORECASE
        )

        self.patterns = [pat_en, pat_zh, pat_en_alt, pat_table, pat_price_only]

    def _normalize_side(self, text: str) -> Optional[str]:
        s = (text or "").lower()
        if any(kw in s for kw in self.long_keywords):
            return "LONG"
        if any(kw in s for kw in self.short_keywords):
            return "SHORT"
        return None

    # 三态判定，futures 优先；None 表示未知
    def _detect_market_type(self, text: str) -> Optional[bool]:
        t = (text or "").lower()
        has_spot = any(h.lower() in t for h in SPOT_HINTS)
        has_fut  = any(h.lower() in t for h in FUTURES_HINTS)
        if has_fut and not has_spot:
            return False   # 明确期货
        if has_spot and not has_fut:
            return True    # 明确现货
        return None        # 不确定

    def _parse_price_value(self, txt: str) -> Tuple[Optional[float], List[float]]:
        if not txt:
            return None, []
        if re.search(r'entry\s*price|入场价|入場價|建仓价|開倉價|开仓价', txt, re.IGNORECASE):
            return None, []
        cleaned = re.sub(r'[^\d.,\-/\s()]', '', txt)
        m_avg = re.search(r'avg[:：\s]*([0-9]+(?:\.[0-9]+)?)', txt, re.IGNORECASE)
        if m_avg:
            try:
                return float(m_avg.group(1)), []
            except ValueError:
                pass
        m_rng = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*[\-/]\s*([0-9]+(?:\.[0-9]+)?)', cleaned)
        if m_rng:
            try:
                a = float(m_rng.group(1)); b = float(m_rng.group(2))
                return (a + b) / 2.0, []
            except ValueError:
                pass
        nums = re.findall(r'[0-9]+(?:\.[0-9]+)?', cleaned)
        if not nums:
            return None, []
        vals = [float(n) for n in nums]
        return vals[0], vals[1:]

    def _calc_conf(self, has_side: bool, has_stop: bool, has_tp: bool, line: str) -> float:
        c = 0.5
        if has_side: c += 0.2
        if has_stop: c += 0.15
        if has_tp:   c += 0.10
        terms = ['entry', 'entry price', '开仓', '入场', '进场', '止损', '止盈', '目标', 'take profit', 'stop loss']
        if any(t in (line or "").lower() for t in terms):
            c += 0.05
        return min(c, 1.0)

    def _is_heading_line(self, line: str) -> bool:
        low = (line or "").lower()
        return any(h.lower() in low for h in HEADING_HINTS)

    def parse(self, full_text: str) -> List[ParsedSignal]:
        if not full_text:
            return []

        # 解析文本去除市场标签，但市场判定仍用原文
        clean_text = full_text
        for tag in SPOT_HINTS + FUTURES_HINTS:
            clean_text = clean_text.replace(tag, "")

        orig_raw = [ln.strip() for ln in (full_text or "").splitlines() if ln and ln.strip()]
        clean_raw = [ln.strip() for ln in (clean_text or "").splitlines() if ln and ln.strip()]

        n = min(len(orig_raw), len(clean_raw))
        orig_raw = orig_raw[:n]
        clean_raw = clean_raw[:n]

        signals: List[ParsedSignal] = []

        # 全文只作弱提示；默认按期货处理
        ctx_mt = self._detect_market_type(full_text)
        is_spot_context = (ctx_mt is True)  # True=现货；None/False -> 默认期货
        lines: List[str] = []
        market_lines: List[str] = []

        for i in range(n):
            orig_ln = orig_raw[i]
            clean_ln = clean_raw[i].replace('、', ',').replace('：', ':')

            if self._is_heading_line(orig_ln):
                # 仅用于上下文提示
                ctx_line_mt = self._detect_market_type(orig_ln)
                if ctx_line_mt is True:
                    is_spot_context = True
                elif ctx_line_mt is False:
                    is_spot_context = False
                lines.append("")         # 跳过解析
                market_lines.append("")  # 保持索引一致
                continue

            lines.append(clean_ln)
            market_lines.append(orig_ln)

        last_side: Optional[str] = None
        last_symbol: Optional[str] = None
        last_market_spot: Optional[bool] = is_spot_context

        for idx, line in enumerate(lines, 1):
            if not line or len(line) < 3:
                continue

            # 行内显式市场类型优先覆盖
            line_mt = self._detect_market_type(market_lines[idx-1])
            if line_mt is True:
                last_market_spot = True
            elif line_mt is False:
                last_market_spot = False

            matched = False
            for pattern in self.patterns:
                m = pattern.match(line)
                if not m:
                    continue
                md = m.groupdict()

                side = self._normalize_side(md.get('side', ''))

                symbol_raw = md.get('symbol') or md.get('prefix_symbol') or md.get('maybe_symbol') or ""
                symbol = normalize_symbol_from_text(symbol_raw or line)

                entry_text = md.get('entry', '')
                entry, extra_from_entry = self._parse_price_value(entry_text)
                if entry is None or entry <= 0:
                    continue

                stop_text = md.get('stop', '') or ''
                if re.search(r'entry\s*price|入场价|入場價|建仓价|開倉價|开仓价', stop_text, re.IGNORECASE):
                    stop = entry
                else:
                    stop, _ = self._parse_price_value(stop_text) if stop_text else (None, [])

                tp_text = md.get('tp', '') or ''
                tps: List[float] = []
                if tp_text:
                    tps = [float(x) for x in re.findall(r'[0-9]+(?:\.[0-9]+)?', tp_text.replace('、', ','))]
                if extra_from_entry:
                    tps.extend(extra_from_entry)

                if not side:
                    side = last_side or "LONG"
                if not symbol:
                    symbol = last_symbol or normalize_symbol_from_text(line)

                if not symbol:
                    continue

                conf = self._calc_conf(has_side=bool(side), has_stop=bool(stop), has_tp=bool(tps), line=line)

                try:
                    sig = ParsedSignal(
                        side=side,
                        symbol=symbol,
                        entry=entry,
                        stop=stop,
                        is_spot=bool(last_market_spot),
                        take_profits=tps,
                        raw_line=market_lines[idx-1] or line,
                        confidence=conf
                    )
                    signals.append(sig)
                    last_side = side
                    last_symbol = symbol
                    matched = True
                    break
                except Exception as e:
                    logger.debug(f"解析行失败[{idx}] {line[:100]} -> {e}")
                    matched = True
                    break

            if not matched:
                logger.debug(f"无匹配的行[{idx}]: {line[:120]}")

        uniq: List[ParsedSignal] = []
        seen = set()
        for s in sorted(signals, key=lambda x: x.confidence, reverse=True):
            fp = (s.symbol, s.side, round(s.entry, 2))
            if fp in seen:
                continue
            seen.add(fp)
            uniq.append(s)
        return uniq

# ====== 风险管理器 ======
class EnhancedRiskManager:
    def __init__(self, risk_per_trade_percent: float, max_leverage: int):
        self.risk_per_trade_percent = risk_per_trade_percent
        self.max_leverage = max_leverage
        self.min_position_usd = 5.0

    async def calculate_position_size(self, entry: float, stop: Optional[float], equity: float,
                                      contract_info: Optional[ContractInfo] = None) -> Optional[Dict[str, Any]]:
        try:
            if equity <= 0:
                logger.error("账户权益不足")
                return None
            if not stop or stop <= 0:
                stop = entry * 0.98
            risk_amount_usd = equity * self.risk_per_trade_percent
            stop_distance = abs(entry - stop)
            if stop_distance <= 0:
                logger.error("止损距离无效")
                return None

            base_size = risk_amount_usd / stop_distance

            if contract_info:
                if base_size < contract_info.min_trade_num:
                    base_size = contract_info.min_trade_num
                if contract_info.max_trade_num and base_size > contract_info.max_trade_num:
                    base_size = contract_info.max_trade_num
                position_value = base_size * entry
                if position_value < contract_info.min_order_usd:
                    base_size = contract_info.min_order_usd / entry

            position_value = base_size * entry
            required_margin = position_value / self.max_leverage
            max_margin = equity * 0.8
            if required_margin > max_margin:
                base_size = (max_margin * self.max_leverage) / entry
                position_value = base_size * entry
                required_margin = position_value / self.max_leverage

            if position_value < self.min_position_usd:
                logger.warning(f"持仓价值({position_value:.2f} USD) < 最小要求({self.min_position_usd} USD)")

            return {
                "size": base_size,
                "risk_amount": risk_amount_usd,
                "stop_distance": stop_distance,
                "position_value": position_value,
                "required_margin": required_margin,
                "leverage_used": position_value / required_margin if required_margin else 0,
                "risk_reward_ratio": stop_distance / entry if entry > 0 else 0,
            }
        except Exception as e:
            logger.error(f"❌ 风险计算异常: {e}")
            return None

# ====== 执行器 ======
class EnhancedTradeExecutor:
    def __init__(self, bitget_client: BitgetAPIClient, risk_manager: EnhancedRiskManager):
        self.bitget = bitget_client
        self.risk_manager = risk_manager

    async def execute_signal(self, signal: ParsedSignal) -> Dict[str, bool]:
        try:
            logger.info(f"📌 市场类型判定: {'Spot' if signal.is_spot else 'Futures'} | 行: {signal.raw_line[:80]}...")
            if signal.is_spot:
                logger.info(f"🛈 跳过现货信号: {signal.symbol} {signal.side} @ {signal.entry}")
                return {"attempted": False, "success": False}

            if not await self.bitget.validate_symbol(signal.symbol):
                logger.error(f"❌ 交易对验证失败: {signal.symbol}")
                return {"attempted": True, "success": False}

            ct = await self.bitget.get_contract_info(signal.symbol)
            if not ct:
                logger.error(f"❌ 无法获取合约信息: {signal.symbol}")
                return {"attempted": True, "success": False}

            acc = await self.bitget.get_account_info(signal.symbol)
            if acc.get("code") != "00000":
                logger.error(f"❌ 获取账户信息失败: {acc}")
                return {"attempted": True, "success": False}
            equity = float(acc.get("data", {}).get("usdtEquity", 0))
            if equity <= 0:
                logger.error("❌ 账户权益不足")
                return {"attempted": True, "success": False}

            pos = await self.risk_manager.calculate_position_size(signal.entry, signal.stop, equity, ct)
            if not pos:
                logger.error("❌ 风险计算失败")
                return {"attempted": True, "success": False}

            size_str = self.bitget.format_size(pos["size"], signal.symbol)
            _ = self.bitget.format_price(signal.entry, signal.symbol)

            lev = await self.bitget.set_leverage(signal.symbol, MAX_LEVERAGE)
            if lev.get("code") != "00000":
                logger.warning(f"⚠️ 设置杠杆失败: {lev}")

            side_map = {"LONG": ("buy", "open"), "SHORT": ("sell", "open")}
            order_side, trade_side = side_map[signal.side]
            client_oid = f"signal_{signal.symbol}_{int(time.time()*1000)}"

            logger.info(f"🚀 开仓: {signal.side} {signal.symbol} 数量: {size_str} (entry ~ {signal.entry})")

            order = await self.bitget.place_order(signal.symbol, order_side, trade_side, "market", size_str, client_oid=client_oid)
            if order.get("code") != "00000":
                logger.error(f"❌ 开仓失败: {order}")
                return {"attempted": True, "success": False}

            order_id = order.get("data", {}).get("orderId")
            logger.info(f"✅ 开仓成功，订单ID: {order_id}")

            if signal.stop and signal.stop > 0:
                await self._set_stop_loss(signal, size_str)

            if signal.take_profits:
                await self._set_take_profits(signal, size_str)

            return {"attempted": True, "success": True}
        except Exception as e:
            logger.error(f"❌ 执行交易信号异常: {e}")
            return {"attempted": True, "success": False}

    async def _set_stop_loss(self, signal: ParsedSignal, size: str):
        try:
            await asyncio.sleep(1)
            sl_side = "sell" if signal.side == "LONG" else "buy"
            stop_px = self.bitget.format_price(signal.stop, signal.symbol)
            res = await self.bitget.place_stop_plan_order(signal.symbol, sl_side, stop_px, size)
            if res.get("code") == "00000":
                logger.info(f"🛡️ 止损设置成功: {stop_px}")
            else:
                logger.error(f"❌ 止损设置失败: {res}")
        except Exception as e:
            logger.error(f"❌ 设置止损异常: {e}")

    async def _set_take_profits(self, signal: ParsedSignal, size: str):
        try:
            if not signal.take_profits:
                return
            tp_count = len(signal.take_profits)
            base_size = float(size)
            for i, tp_price in enumerate(signal.take_profits, 1):
                tp_sz = base_size / tp_count
                tp_size_str = self.bitget.format_size(tp_sz, signal.symbol)
                tp_px = self.bitget.format_price(tp_price, signal.symbol)
                tp_side = "sell" if signal.side == "LONG" else "buy"
                res = await self.bitget.place_stop_plan_order(signal.symbol, tp_side, tp_px, tp_size_str)
                if res.get("code") == "00000":
                    logger.info(f"🎯 止盈{i}设置成功: {tp_px}")
                else:
                    logger.error(f"❌ 止盈{i}设置失败: {res}")
                await asyncio.sleep(0.4)
        except Exception as e:
            logger.error(f"❌ 设置止盈异常: {e}")

# ====== Discord 文本提取 ======
def _get(obj: Dict[str, Any], *path, default=None):
    cur = obj
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur

def extract_all_text_content(message: Dict[str, Any]) -> List[str]:
    content_parts: List[str] = []
    # 主文本
    if content := message.get("content"):
        content_parts.append(content)

    # Mentions (用户/角色/频道名)
    mentions = message.get("mentions", []) or []
    for m in mentions:
        name = m.get("global_name") or m.get("username") or m.get("nick")
        if name:
            content_parts.append(f"@{name}")
    if roles := message.get("mention_roles"):
        for r in roles:
            content_parts.append(f"@role:{r}")
    if chs := message.get("mention_channels") or []:
        for ch in chs:
            if isinstance(ch, dict) and ch.get("name"):
                content_parts.append(f"#{ch['name']}")

    # Stickers
    if "sticker_items" in message:
        for st in message.get("sticker_items", []):
            nm = st.get("name")
            if nm:
                content_parts.append(f"[sticker] {nm}")

    # 交互（应用命令等）
    if message.get("interaction"):
        name = _get(message, "interaction", "name") or _get(message, "interaction", "command_name")
        if name:
            content_parts.append(f"/{name}")

    # Embeds
    for embed in message.get("embeds", []) or []:
        if title := embed.get("title"):
            if embed.get("url"):
                content_parts.append(f"{title} ({embed.get('url')})")
            else:
                content_parts.append(title)
        if description := embed.get("description"):
            content_parts.append(description)
        author_name = _get(embed, "author", "name")
        if author_name:
            content_parts.append(author_name)
        author_url = _get(embed, "author", "url")
        if author_url:
            content_parts.append(author_url)
        provider_name = _get(embed, "provider", "name")
        if provider_name:
            content_parts.append(provider_name)
        footer_text = _get(embed, "footer", "text")
        if footer_text:
            content_parts.append(footer_text)
        if url := embed.get("url"):
            content_parts.append(url)
        # 字段
        for field in embed.get("fields", []) or []:
            if name := field.get("name"):
                content_parts.append(name)
            if value := field.get("value"):
                content_parts.append(value)

    # 组件（按钮/文本）
    for comp in message.get("components", []) or []:
        try:
            for row in comp.get("components", []) or []:
                txt = row.get("label") or row.get("value") or row.get("placeholder")
                if txt:
                    content_parts.append(txt)
        except Exception:
            pass

    # 附件
    for att in message.get("attachments", []) or []:
        if description := att.get("description"):
            content_parts.append(description)
        if filename := att.get("filename"):
            content_parts.append(f"文件: {filename}")

    # 引用（如果上层已补全 _ref_full，会递归采集）
    if ref := message.get("_ref_full"):
        content_parts.extend(extract_all_text_content(ref))

    # 清洗
    out = []
    for part in content_parts:
        if not part or not str(part).strip():
            continue
        out.append(str(part).strip())
    return out

async def get_complete_message_content(session: aiohttp.ClientSession, token: str, message: Dict[str, Any]) -> str:
    all_content = extract_all_text_content(message)
    merged = "\n".join(all_content)
    return merged.strip()

# ====== Discord 辅助 ======
def get_auth_header(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bot {token.strip()}",
        "User-Agent": "DiscordBot (Python/aiohttp)",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

def iso_to_local_str(ts: Optional[str]) -> str:
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone()
        return dt.strftime('%Y-%m-%d %H:%M:%S.%f %Z')
    except Exception:
        return ts or ""

def user_tag(u: Dict[str, Any]) -> str:
    name = u.get("username", "Unknown")
    disc = u.get("discriminator")
    return f"{name}" if disc in (None, "0") else f"{name}#{disc}"

async def fetch_channel(session: aiohttp.ClientSession, token: str, channel_id: str) -> Optional[Dict[str, Any]]:
    url = f"{DISCORD_API_BASE}/channels/{channel_id}"
    try:
        async with session.get(url, headers=get_auth_header(token)) as resp:
            if resp.status == 200:
                return await resp.json()
    except Exception:
        pass
    return None

async def fetch_message_by_id(session: aiohttp.ClientSession, token: str, channel_id: str, message_id: str) -> Optional[Dict[str, Any]]:
    url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}"
    try:
        async with session.get(url, headers=get_auth_header(token)) as resp:
            if resp.status == 200:
                return await resp.json()
    except Exception:
        pass
    return None

async def fetch_referenced_message(session: aiohttp.ClientSession, token: str, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    # 优先用 gateway 提供的 referenced_message（但经常是部分或None）
    ref_msg = message.get("referenced_message")
    ref_info = message.get("message_reference", {}) or {}
    if ref_msg and isinstance(ref_msg, dict) and (ref_msg.get("content") or ref_msg.get("embeds")):
        return ref_msg
    # REST 查询被引用消息（可跨频道）
    ref_channel_id = ref_info.get("channel_id") or message.get("channel_id")
    ref_message_id = ref_info.get("message_id")
    if ref_channel_id and ref_message_id:
        return await fetch_message_by_id(session, token, ref_channel_id, ref_message_id)
    return None

async def fetch_recent_messages(session: aiohttp.ClientSession, token: str, channel_id: str, limit: int = 50,
                                before: Optional[str] = None, after: Optional[str] = None, around: Optional[str] = None) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": min(max(limit, 1), 100)}
    if before: params["before"] = before
    if after: params["after"] = after
    if around: params["around"] = around
    url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
    try:
        async with session.get(url, headers=get_auth_header(token), params=params) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                logger.warning(f"⚠️ 拉取历史失败: channel={channel_id} http={resp.status}")
    except Exception as e:
        logger.error(f"❌ 拉取历史异常: {e}")
    return []

# ====== 交易管道 ======
class EnhancedTradingPipeline:
    def __init__(self):
        self.parser = EnhancedMultiSignalParser()
        self.bitget: Optional[BitgetAPIClient] = None
        self.executor: Optional[EnhancedTradeExecutor] = None
        self.processed_count = 0
        self.executed_count = 0
        self.success_count = 0
        self.enabled = True

    async def initialize(self):
        if _is_placeholder(DISCORD_BOT_TOKEN):
            raise ValueError("❌ 未配置 DISCORD_BOT_TOKEN（请在代码常量处填写）")
        if any(_is_placeholder(x) for x in (BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE)):
            raise ValueError("❌ Bitget API 配置不完整（请在代码常量处填写 API Key/Secret/Passphrase）")

        try:
            self.bitget = BitgetAPIClient(BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE)
            await self.bitget.__aenter__()
            await self.bitget._refresh_contract_cache()

            test = await self.bitget.get_account_info(DEFAULT_SYMBOL)
            if test.get("code") != "00000":
                raise ValueError(f"❌ Bitget 连接失败: {test.get('msg')} (检查 API 密钥是否有效)")
            equity = test.get("data", {}).get("usdtEquity", 0)
            logger.info(f"🎉 Bitget 连接成功! 账户权益: {equity} USDT")

            self.executor = EnhancedTradeExecutor(
                self.bitget,
                EnhancedRiskManager(RISK_PER_TRADE_PERCENT, MAX_LEVERAGE)
            )
        except Exception as e:
            logger.error(f"❌ 初始化交易管道失败: {e}")
            self.enabled = False
            raise

    async def close(self):
        if self.bitget:
            await self.bitget.__aexit__(None, None, None)

    async def process_message(self, session: aiohttp.ClientSession, token: str,
                              message: Dict[str, Any], channel_info: Optional[Dict[str, Any]] = None) -> bool:
        try:
            # 引用消息补全（REST）
            try:
                ref_full = await fetch_referenced_message(session, token, message)
                if ref_full:
                    message["_ref_full"] = ref_full
            except Exception as e:
                logger.debug(f"引用消息补全过程异常: {e}")

            full_content = await get_complete_message_content(session, token, message)
            if not full_content or len(full_content.strip()) < 3:
                logger.debug("消息内容为空或过短，跳过处理")
                return False

            # 频道默认市场强制覆盖（通过在文本顶部注入标签实现）
            force_spot = message.get("_force_spot", None)
            if isinstance(force_spot, bool):
                prefix = "@✍active-现货\n" if force_spot else "@🧲active-futures\n"
                full_content = prefix + full_content

            signals = self.parser.parse(full_content)
            if not signals:
                logger.debug("未检测到交易信号")
                return False

            valid = [s for s in signals if s.confidence >= 0.6]
            if not valid:
                logger.info(f"🔍 检测到 {len(signals)} 个信号，但置信度不足 (< 0.6)")
                return False

            logger.info(f"🎯 检测到 {len(valid)} 个有效交易信号")
            any_success = False

            for i, sig in enumerate(valid, 1):
                self.processed_count += 1
                logger.info(f"  [{i}] {sig.side} {sig.symbol} @ {sig.entry:.6f} | SL: {sig.stop if sig.stop else 'None'} | TP: {sig.take_profits or 'None'} | spot={sig.is_spot} | conf={sig.confidence:.2f}")
                logger.info(f"      原始: {sig.raw_line[:140]}...")

                if self.enabled and self.executor:
                    result = await self.executor.execute_signal(sig)
                    if result.get("attempted"):
                        self.executed_count += 1
                        if result.get("success"):
                            self.success_count += 1
                            any_success = True
                            logger.info(f"✅ 信号 [{i}] 执行成功")
                        else:
                            logger.error(f"❌ 信号 [{i}] 执行失败")
                    else:
                        logger.info(f"⏭️ 信号 [{i}] 未尝试下单（例如现货/规则过滤）")
                else:
                    logger.warning("⚠️ 交易执行器未启用，跳过实际下单")

            sr = (self.success_count / self.executed_count * 100) if self.executed_count > 0 else 0
            logger.info(f"📊 统计: 已处理 {self.processed_count} | 已尝试执行 {self.executed_count} | 成功率 {sr:.1f}%")
            return any_success
        except Exception as e:
            logger.error(f"❌ 处理消息异常: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        return {
            "processed": self.processed_count,
            "executed": self.executed_count,
            "success": self.success_count,
            "success_rate": (self.success_count / self.executed_count * 100) if self.executed_count > 0 else 0,
            "enabled": self.enabled
        }

# ====== Discord Gateway 客户端 ======
class DiscordGatewayClient:
    def __init__(self, token: str, target_channel_ids: List[str]):
        self.token = token
        self.target_channel_ids = set(target_channel_ids)
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.heartbeat_interval: float = 45.0
        self.seq: Optional[int] = None
        self.session_id: Optional[str] = None
        self.resume_url: Optional[str] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._running = False
        self._parent_cache: Dict[str, Optional[str]] = {}
        self.message_count = 0
        self.bot_user_id: Optional[str] = None
        self._last_heartbeat_ack = True
        self.pipeline = EnhancedTradingPipeline()
        self._seen_message_ids: Set[str] = set()  # 去重

    async def start(self):
        self._running = True
        await self.pipeline.initialize()
        timeout = aiohttp.ClientTimeout(total=60, connect=30, sock_read=30)
        self.session = aiohttp.ClientSession(timeout=timeout)

        if not await self._verify_connection():
            await self.stop()
            return

        # ---- 启动回溯：每个目标频道回读最近 N 条 ----
        await self._backfill_recent_messages(limit=50)

        # ---- 进入网关实时监听 ----
        while self._running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Gateway 连接异常: {e}")
                await asyncio.sleep(5)

        await self.stop()

    async def stop(self):
        self._running = False
        await self.pipeline.close()
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        if self.ws and not self.ws.closed:
            await self.ws.close()
        if self.session and not self.session.closed:
            await self.session.close()

    async def _verify_connection(self) -> bool:
        try:
            async with self.session.get(f"{DISCORD_API_BASE}/users/@me", headers=get_auth_header(self.token)) as resp:
                if resp.status == 200:
                    me = await resp.json()
                    self.bot_user_id = me.get("id")
                    logger.info(f"✅ Discord Bot 认证成功: {me.get('username')}")
                else:
                    raise ValueError(f"❌ Discord Token 验证失败: {resp.status} (检查 Token 是否有效)")
        except Exception as e:
            logger.error(f"❌ Discord Token 验证异常: {e}")
            return False

        accessible = 0
        for cid in self.target_channel_ids:
            ch = await fetch_channel(self.session, self.token, cid)
            if ch:
                accessible += 1
                logger.info(f"✅ 频道可访问: {cid} - #{ch.get('name', '?')}")
            else:
                logger.warning(f"⚠️ 无法访问频道: {cid}")
        if accessible == 0:
            raise ValueError("❌ 所有频道均不可访问，请检查 Bot 权限和 Token")
        return True

    async def _connect_and_listen(self):
        url = self.resume_url or DISCORD_GATEWAY_URL
        self.ws = await self.session.ws_connect(url, max_msg_size=16*1024*1024, compress=0, heartbeat=30)
        async for msg in self.ws:
            if not self._running:
                break
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                    await self._handle_gateway_message(payload)
                except json.JSONDecodeError:
                    logger.error("❌ 无法解析 Gateway 消息")
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                break

    async def _handle_gateway_message(self, payload: Dict[str, Any]):
        op = payload.get("op")
        event_type = payload.get("t")
        data = payload.get("d", {})
        seq = payload.get("s")
        if seq is not None:
            self.seq = seq

        if op == 10:  # Hello
            self.heartbeat_interval = data.get("heartbeat_interval", 45000) / 1000.0
            if self._heartbeat_task and not self._heartbeat_task.done():
                self._heartbeat_task.cancel()
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            await self._identify()
        elif op == 11:  # Heartbeat ACK
            self._last_heartbeat_ack = True
        elif op == 0 and event_type:
            await self._handle_dispatch_event(event_type, data)

    async def _handle_dispatch_event(self, event_type: str, data: Dict[str, Any]):
        if event_type == "READY":
            self.session_id = data.get("session_id")
            self.resume_url = data.get("resume_gateway_url")
            user = data.get("user", {})
            logger.info(f"🎮 READY: {user.get('username')} 已连接")
        elif event_type == "MESSAGE_CREATE":
            await self._handle_message_create(data)

    async def _identify(self):
        payload = {
            "op": 2,
            "d": {
                "token": self.token,
                "intents": DISCORD_INTENTS,
                "properties": {"$os": "linux", "$browser": "enhanced_trading_bot", "$device": "enhanced_trading_bot"}
            }
        }
        await self.ws.send_str(json.dumps(payload))

    async def _heartbeat_loop(self):
        try:
            await self._send_heartbeat()
            while self._running and self.ws and not self.ws.closed:
                await asyncio.sleep(self.heartbeat_interval)
                if not self._last_heartbeat_ack:
                    logger.error("❌ 心跳超时，关闭连接")
                    await self.ws.close(code=1000, message=b'Heartbeat timeout')
                    break
                await self._send_heartbeat()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"❌ 心跳循环异常: {e}")

    async def _send_heartbeat(self):
        if self.ws and not self.ws.closed:
            payload = {"op": 1, "d": self.seq}
            await self.ws.send_str(json.dumps(payload))
            self._last_heartbeat_ack = False

    async def _is_target_channel_or_thread(self, channel_id: str) -> bool:
        if channel_id in self.target_channel_ids:
            return True
        if channel_id in self._parent_cache:
            parent_id = self._parent_cache[channel_id]
            return parent_id in self.target_channel_ids
        ch = await fetch_channel(self.session, self.token, channel_id)
        parent_id = ch.get("parent_id") if ch else None
        self._parent_cache[channel_id] = parent_id
        return parent_id in self.target_channel_ids

    async def _handle_message_create(self, message: Dict[str, Any]):
        try:
            message_id = message.get("id")
            if not message_id or message_id in self._seen_message_ids:
                return
            self._seen_message_ids.add(message_id)

            channel_id = message.get("channel_id")
            author = message.get("author", {})

            if not await self._is_target_channel_or_thread(channel_id):
                return

            if author.get("bot") and author.get("id") == self.bot_user_id:
                return

            # 频道默认市场强制覆盖标记
            if FORCE_MARKET_OVERRIDE:
                market = CHANNEL_DEFAULT_MARKET.get(channel_id)
                if market == "spot":
                    message["_force_spot"] = True
                elif market == "futures":
                    message["_force_spot"] = False

            self.message_count += 1
            channel_info = await fetch_channel(self.session, self.token, channel_id)

            # 引用消息在 process_message 内统一补全
            signal_detected = await self.pipeline.process_message(self.session, self.token, message, channel_info)

            self._print_message_summary(message, channel_info, signal_detected)

            await self._save_message_log(message, message_id)

        except Exception as e:
            logger.error(f"❌ 处理消息异常: {e}")

    def _print_message_summary(self, message: Dict[str, Any],
                               channel_info: Optional[Dict[str, Any]] = None,
                               signal_detected: bool = False):
        author = message.get("author", {})
        content = message.get("content", "")
        message_id = message.get("id")
        channel_id = message.get("channel_id")
        timestamp = iso_to_local_str(message.get("timestamp"))

        print("=" * 80)
        print(f"🔔 新消息 #{self.message_count}: {message_id}")
        print(f"⏰ 时间: {timestamp}")
        print(f"📍 频道: {channel_id}")
        if channel_info:
            print(f"📢 频道信息: #{channel_info.get('name', 'unknown')} (type={channel_info.get('type', 'unknown')})")
        print(f"👤 作者: {user_tag(author)} (id={author.get('id')})")
        if author.get('bot'):
            print("🤖 [BOT 用户]")

        if content:
            preview = content[:200] + "..." if len(content) > 200 else content
            print(f"💬 内容: {preview}")
        else:
            print("💬 内容: (无文本内容)")
        # ✅ 修复：括号补齐
        print(
            f"📎 Embeds: {len(message.get('embeds', []) or [])} 个 | "
            f"Attachments: {len(message.get('attachments', []) or [])} 个 | "
            f"Components: {len(message.get('components', []) or [])} 个"
        )

        if message.get("message_reference"):
            print("↩️ 检测到引用消息（已使用 REST 尝试补全解析）")

        print("🎯 ✅ 检测到交易信号并已处理" if signal_detected else "🔍 ❌ 未检测到有效交易信号")
        stats = self.pipeline.get_stats()
        print(f"📊 统计: 处理 {stats['processed']} | 尝试执行 {stats['executed']} | 成功率 {stats['success_rate']:.1f}%")
        print("=" * 80)

    async def _save_message_log(self, message: Dict[str, Any], message_id: str):
        try:
            log_file = LOG_DIR / f"{message_id}.json"
            content = json.dumps(message, ensure_ascii=False, indent=2)
            log_file.write_text(content, encoding="utf-8")
        except Exception as e:
            logger.debug(f"保存消息日志失败: {e}")

    async def _backfill_recent_messages(self, limit: int = 50):
        """启动时回溯每个目标频道最近N条，避免漏单"""
        try:
            for cid in self.target_channel_ids:
                msgs = await fetch_recent_messages(self.session, self.token, cid, limit=limit)
                if not msgs:
                    continue
                # 先老后新处理，避免乱序
                for m in reversed(msgs):
                    mid = m.get("id")
                    if not mid or mid in self._seen_message_ids:
                        continue
                    self._seen_message_ids.add(mid)
                    channel_info = await fetch_channel(self.session, self.token, m.get("channel_id"))
                    # 频道默认市场强制覆盖
                    if FORCE_MARKET_OVERRIDE:
                        market = CHANNEL_DEFAULT_MARKET.get(cid)
                        if market == "spot":
                            m["_force_spot"] = True
                        elif market == "futures":
                            m["_force_spot"] = False
                    await self.pipeline.process_message(self.session, self.token, m, channel_info)
                    await self._save_message_log(m, mid)
                logger.info(f"📥 回溯完成: #{cid} 最近 {len(msgs)} 条")
        except Exception as e:
            logger.error(f"❌ 启动回溯异常: {e}")

# ====== 主程序 ======
async def main():
    print("🚀" + "=" * 80)
    print("🚀 Discord + Bitget 自动化交易系统 v2.3 (修正版 | 常量配置版)")
    print("🚀 新功能: 引用补全 | 启动回溯 | 文本提取更全 | 时间同步&风控保持 | 现货/期货判定修复 | 三态统计")
    print("🚀" + "=" * 80)

    print(f"🔑 Discord Token: {'已配置' if not _is_placeholder(DISCORD_BOT_TOKEN) else '未配置(请在代码常量处填写)'}")
    print(f"🔑 Bitget Key   : {'已配置' if not _is_placeholder(BITGET_API_KEY) else '未配置'}")
    print(f"🔑 Bitget Secret: {'已配置' if not _is_placeholder(BITGET_SECRET_KEY) else '未配置'}")
    print(f"🔑 Bitget Pass  : {'已配置' if not _is_placeholder(BITGET_PASSPHRASE) else '未配置'}")

    if not DISCORD_CHANNEL_IDS:
        print("❌ 错误: 未设置 DISCORD_CHANNEL_IDS")
        return

    print(f"📡 监听/回溯频道: {len(DISCORD_CHANNEL_IDS)} 个")
    for i, cid in enumerate(DISCORD_CHANNEL_IDS, 1):
        print(f"   [{i}] {cid}")

    print(f"⚙️ 交易参数:")
    print(f"   风险比例: {RISK_PER_TRADE_PERCENT * 100}%")
    print(f"   最大杠杆: {MAX_LEVERAGE}x")
    print(f"   默认交易对: {DEFAULT_SYMBOL}")
    print(f"   保证金模式: {MARGIN_MODE}")
    print(f"   频道默认市场覆盖: {'开启' if FORCE_MARKET_OVERRIDE else '关闭'}")

    print("🔄 启动中...")
    client = DiscordGatewayClient(DISCORD_BOT_TOKEN, DISCORD_CHANNEL_IDS)

    try:
        await client.start()
    except KeyboardInterrupt:
        print("\n⏹️ 用户中断程序")
    except Exception as e:
        print(f"\n❌ 程序运行异常: {e}")
        logger.exception("程序异常")
    finally:
        await client.stop()
        print("👋 程序已停止")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\n❌ 程序启动失败: {e}")
        logging.exception("启动异常")
