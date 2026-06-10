import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from .models import MarketType

logger = logging.getLogger(__name__)

DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"
INTENTS = (1 << 0) | (1 << 9) | (1 << 12) | (1 << 15)

MessageHandler = Callable[[str, MarketType | None], Awaitable[None]]


class DiscordGatewayClient:
    def __init__(
        self,
        token: str,
        channel_ids: list[str],
        channel_market_overrides: dict[str, str],
        on_message: MessageHandler,
    ):
        self.token = token
        self.channel_ids = set(channel_ids)
        self.channel_market_overrides = channel_market_overrides
        self.on_message = on_message
        self.session: aiohttp.ClientSession | None = None
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self.seq: int | None = None
        self.heartbeat_interval = 45.0
        self.heartbeat_task: asyncio.Task[None] | None = None
        self.seen_message_ids: set[str] = set()
        self.parent_cache: dict[str, str | None] = {}

    async def start(self) -> None:
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        await self._verify_token()
        await self._connect()

    async def stop(self) -> None:
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
        if self.ws and not self.ws.closed:
            await self.ws.close()
        if self.session:
            await self.session.close()

    async def _connect(self) -> None:
        assert self.session
        async with self.session.ws_connect(DISCORD_GATEWAY_URL, heartbeat=None) as ws:
            self.ws = ws
            async for message in ws:
                if message.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_gateway_payload(json.loads(message.data))
                elif message.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                    break

    async def _handle_gateway_payload(self, payload: dict[str, Any]) -> None:
        op = payload.get("op")
        data = payload.get("d")
        event_type = payload.get("t")
        if payload.get("s") is not None:
            self.seq = payload["s"]
        if op == 10:
            self.heartbeat_interval = data.get("heartbeat_interval", 45_000) / 1000
            self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            await self._identify()
        elif op == 0 and event_type == "MESSAGE_CREATE":
            await self._handle_message(data)

    async def _identify(self) -> None:
        assert self.ws
        await self.ws.send_json(
            {
                "op": 2,
                "d": {
                    "token": self.token,
                    "intents": INTENTS,
                    "properties": {
                        "$os": "windows",
                        "$browser": "traderbot",
                        "$device": "traderbot",
                    },
                },
            }
        )

    async def _heartbeat_loop(self) -> None:
        assert self.ws
        while not self.ws.closed:
            await self.ws.send_json({"op": 1, "d": self.seq})
            await asyncio.sleep(self.heartbeat_interval)

    async def _handle_message(self, message: dict[str, Any]) -> None:
        message_id = message.get("id")
        channel_id = message.get("channel_id")
        if not message_id or message_id in self.seen_message_ids or not channel_id:
            return
        self.seen_message_ids.add(message_id)
        if not await self._is_target_channel(channel_id):
            return
        content = extract_text(message)
        if not content.strip():
            return
        forced_market = self._forced_market(channel_id)
        await self.on_message(content, forced_market)

    async def _is_target_channel(self, channel_id: str) -> bool:
        if channel_id in self.channel_ids:
            return True
        parent_id = self.parent_cache.get(channel_id)
        if parent_id is not None:
            return parent_id in self.channel_ids
        channel = await self._fetch_channel(channel_id)
        parent_id = channel.get("parent_id") if channel else None
        self.parent_cache[channel_id] = parent_id
        return parent_id in self.channel_ids

    async def _fetch_channel(self, channel_id: str) -> dict[str, Any] | None:
        assert self.session
        async with self.session.get(
            f"{DISCORD_API_BASE}/channels/{channel_id}",
            headers={"Authorization": f"Bot {self.token}"},
        ) as response:
            if response.status == 200:
                return await response.json()
            logger.warning("unable to fetch channel %s status=%s", channel_id, response.status)
            return None

    async def _verify_token(self) -> None:
        assert self.session
        async with self.session.get(
            f"{DISCORD_API_BASE}/users/@me",
            headers={"Authorization": f"Bot {self.token}"},
        ) as response:
            if response.status != 200:
                raise RuntimeError(f"Discord token verification failed: HTTP {response.status}")

    def _forced_market(self, channel_id: str) -> MarketType | None:
        raw = self.channel_market_overrides.get(channel_id)
        if raw == MarketType.SPOT.value:
            return MarketType.SPOT
        if raw == MarketType.FUTURES.value:
            return MarketType.FUTURES
        return None


def extract_text(message: dict[str, Any]) -> str:
    parts: list[str] = []
    if message.get("content"):
        parts.append(message["content"])
    for embed in message.get("embeds") or []:
        for key in ("title", "description"):
            if embed.get(key):
                parts.append(str(embed[key]))
        for field in embed.get("fields") or []:
            if field.get("name"):
                parts.append(str(field["name"]))
            if field.get("value"):
                parts.append(str(field["value"]))
    return "\n".join(parts)
