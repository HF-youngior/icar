from __future__ import annotations

import asyncio
from typing import Any

from ..config import CarConfig
from .base import CarAdapter


class TcpCarAdapter(CarAdapter):
    name = "tcp"

    def __init__(self, config: CarConfig) -> None:
        self.config = config

    async def connect(self) -> None:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.config.host, self.config.port),
            timeout=self.config.command_timeout_sec,
        )
        writer.close()
        await writer.wait_closed()

    async def disconnect(self) -> None:
        return None

    async def _send(self, key: str, **values: Any) -> dict[str, Any]:
        template = self.config.command_map.get(key)
        if not template:
            raise ValueError(f"No TCP command template for {key}")
        payload = template.format(**values).encode("utf-8")
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.config.host, self.config.port),
            timeout=self.config.command_timeout_sec,
        )
        writer.write(payload)
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        return {"ok": True, "adapter": self.name, "command": key, "bytes": len(payload)}

    async def manual_control(self, direction: str, speed: float) -> dict[str, Any]:
        return await self._send(direction, speed=speed)

    async def stop(self) -> dict[str, Any]:
        return await self._send("stop")

    async def emergency_stop(self, reason: str = "web") -> dict[str, Any]:
        return await self._send("emergency_stop", reason=reason)

    async def send_navigation_goal(self, point: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("TCP navigation needs the car protocol from the course material.")

