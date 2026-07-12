from __future__ import annotations

from typing import Any

from .base import CarAdapter


class SimulatedCarAdapter(CarAdapter):
    name = "simulated"

    def __init__(self) -> None:
        self.connected = True

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def manual_control(self, direction: str, speed: float) -> dict[str, Any]:
        return {"ok": True, "adapter": self.name, "direction": direction, "speed": speed}

    async def stop(self) -> dict[str, Any]:
        return {"ok": True, "adapter": self.name, "direction": "stop", "speed": 0}

    async def emergency_stop(self, reason: str = "web") -> dict[str, Any]:
        return {"ok": True, "adapter": self.name, "reason": reason, "speed": 0}

    async def send_navigation_goal(self, point: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "adapter": self.name, "point": point.get("id")}

    async def auxiliary_control(self, action: str, **values: Any) -> dict[str, Any]:
        return {"ok": True, "adapter": self.name, "action": action, "values": values}
