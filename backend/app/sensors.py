from __future__ import annotations

import asyncio
import math
import random
from typing import Any

from .config import AppConfig
from .state import StateHub


class SensorService:
    def __init__(self, config: AppConfig, state: StateHub) -> None:
        self.config = config
        self.state = state
        self._tick = 0
        self._task: asyncio.Task[None] | None = None
        self.thresholds = {
            "temperature": {"warning": 30, "danger": 36},
            "humidity": {"warning": 70, "danger": 82},
            "light": {"warning_low": 90, "danger_low": 40},
            "gas": {"warning": 0.35, "danger": 0.65},
            "pm25": {"warning": 75, "danger": 115},
        }

    def start_background(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.sensor_tick_sec)
            await self.generate_once()

    async def generate_once(self) -> None:
        self._tick += 1
        wave = math.sin(self._tick / 8)
        values = {
            "temperature": round(24.2 + wave * 1.8 + random.uniform(-0.25, 0.25), 1),
            "humidity": round(48 + math.sin(self._tick / 10) * 7 + random.uniform(-1.2, 1.2), 0),
            "light": round(360 + math.sin(self._tick / 5) * 180 + random.uniform(-18, 18), 0),
            "gas": round(max(0.02, 0.09 + (0.28 if self._tick % 47 > 40 else 0) + random.uniform(-0.02, 0.02)), 2),
            "pm25": round(max(8, 24 + math.sin(self._tick / 6) * 18 + random.uniform(-3, 3)), 0),
        }
        for name, value in values.items():
            level = self._level(name, value)
            await self.state.update_sensor(name, {"value": value, "level": level})

    def _level(self, name: str, value: float) -> str:
        threshold = self.thresholds[name]
        if "danger_low" in threshold and value <= threshold["danger_low"]:
            return "danger"
        if "warning_low" in threshold and value <= threshold["warning_low"]:
            return "warning"
        if value >= threshold.get("danger", float("inf")):
            return "danger"
        if value >= threshold.get("warning", float("inf")):
            return "warning"
        return "normal"

