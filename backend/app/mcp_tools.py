from __future__ import annotations

import asyncio
import time
from typing import Any

from .adapters.base import CarAdapter
from .state import StateHub


class McpToolService:
    fixed_speed_mps = 0.2
    command_interval_sec = 0.18

    def __init__(self, state: StateHub, adapter: CarAdapter) -> None:
        self.state = state
        self.adapter = adapter

    def tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "move_distance",
                "description": "Move the car forward or backward by a target distance in meters at a fixed speed of 0.2 m/s.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "direction": {
                            "type": "string",
                            "enum": ["forward", "backward"],
                            "description": "Movement direction.",
                        },
                        "meters": {
                            "type": "number",
                            "minimum": 0.1,
                            "maximum": 20,
                            "description": "Distance to move in meters.",
                        },
                    },
                    "required": ["direction", "meters"],
                },
            }
        ]

    async def move_distance(self, direction: str, meters: float) -> dict[str, Any]:
        direction = str(direction).lower().strip()
        meters = float(meters)
        if direction not in {"forward", "backward"}:
            raise ValueError("direction must be 'forward' or 'backward'")
        if meters <= 0:
            raise ValueError("meters must be greater than 0")
        if meters > 20:
            raise ValueError("meters is too large for a single tool call")

        duration_sec = meters / self.fixed_speed_mps
        started_at = time.monotonic()

        await self.state.update_robot(
            connected=True,
            mode="tool_move",
            speed=self.fixed_speed_mps,
            target=f"{direction}:{meters:.2f}m",
            last_command=f"move_distance:{direction}:{meters:.2f}",
            last_error=None,
        )

        try:
            while True:
                elapsed = time.monotonic() - started_at
                if elapsed >= duration_sec:
                    break
                await self.adapter.manual_control(direction, self.fixed_speed_mps)
                await asyncio.sleep(min(self.command_interval_sec, max(0.01, duration_sec - elapsed)))
            await self.adapter.stop()
        except Exception:
            await self.state.update_robot(speed=0, mode="offline")
            raise

        await self.state.update_robot(
            speed=0,
            mode="standby",
            target=None,
            last_command="stop",
        )
        await self.state.add_report(
            title=f"移动工具 {direction}",
            summary=f"按固定速度 {self.fixed_speed_mps:.1f}m/s 移动 {meters:.2f} 米。",
            details={
                "tool": "move_distance",
                "direction": direction,
                "meters": meters,
                "speed_mps": self.fixed_speed_mps,
                "duration_sec": round(duration_sec, 3),
            },
        )
        return {
            "ok": True,
            "tool": "move_distance",
            "direction": direction,
            "meters": meters,
            "speed_mps": self.fixed_speed_mps,
            "duration_sec": round(duration_sec, 3),
        }
