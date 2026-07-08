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
        payload = self._command_payload(key).encode("utf-8")
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.config.host, self.config.port),
            timeout=self.config.command_timeout_sec,
        )
        writer.write(payload)
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        return {"ok": True, "adapter": self.name, "command": key, "bytes": len(payload)}

    def _command_payload(self, key: str) -> str:
        direction_map = {
            "stop": 0,
            "forward": 1,
            "backward": 2,
            "left": 5,
            "right": 6,
            "emergency_stop": 7,
        }
        if key not in direction_map:
            raise ValueError(f"Unsupported TCP command: {key}")
        return self._encode_frame("15", self._hex(direction_map[key]))

    def _encode_frame(self, command: str, info: str = "") -> str:
        size = self._hex(len(info) + 2)
        body = f"01{command}{size}{info}"
        checksum = 0
        for index in range(0, len(body), 2):
            checksum = (checksum + int(body[index:index + 2], 16)) % 256
        return f"${body}{self._hex(checksum)}#"

    def _hex(self, value: int, width: int = 2) -> str:
        return f"{value:0{width}X}"

    async def manual_control(self, direction: str, speed: float) -> dict[str, Any]:
        return await self._send(direction, speed=speed)

    async def stop(self) -> dict[str, Any]:
        return await self._send("stop")

    async def emergency_stop(self, reason: str = "web") -> dict[str, Any]:
        return await self._send("emergency_stop", reason=reason)

    async def send_navigation_goal(self, point: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("TCP navigation needs the car protocol from the course material.")
