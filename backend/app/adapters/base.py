from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CarAdapter(ABC):
    name = "base"

    @abstractmethod
    async def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def manual_control(self, direction: str, speed: float) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def emergency_stop(self, reason: str = "web") -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def send_navigation_goal(self, point: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    async def auxiliary_control(self, action: str, **values: Any) -> dict[str, Any]:
        raise NotImplementedError(f"{self.name} does not support auxiliary control: {action}")
