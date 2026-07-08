from __future__ import annotations

import asyncio
import itertools
import random

from .config import AppConfig
from .state import StateHub


class VisionService:
    def __init__(self, config: AppConfig, state: StateHub) -> None:
        self.config = config
        self.state = state
        self._task: asyncio.Task[None] | None = None
        self._events = itertools.cycle([
            {"label": "person", "label_zh": "人员", "confidence": 0.86, "risk": "warning"},
            {"label": "cat", "label_zh": "宠物", "confidence": 0.78, "risk": "normal"},
            {"label": "door_open", "label_zh": "门窗未关闭", "confidence": 0.71, "risk": "warning"},
            {"label": "clear", "label_zh": "未发现异常", "confidence": 0.96, "risk": "normal"},
        ])

    def start_background(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.vision_tick_sec)
            await self.detect_once()

    async def detect_once(self) -> dict:
        base = next(self._events)
        event = {
            **base,
            "bbox": [
                random.randint(80, 220),
                random.randint(40, 140),
                random.randint(260, 420),
                random.randint(220, 380),
            ],
            "image_url": "/assets/sample-detection.svg",
            "source": "simulated",
        }
        await self.state.add_vision_event(event)
        if event["risk"] == "warning":
            await self.state.add_alarm(
                alarm_type=f"vision_{event['label']}",
                level="warning",
                message=f"视觉检测到{event['label_zh']}，请确认家庭环境。",
                source="vision",
                metadata=event,
            )
        return event

