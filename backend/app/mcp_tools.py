from __future__ import annotations

import asyncio
import time
from typing import Any

from .adapters.base import CarAdapter
from .state import StateHub
from .tts import TencentTtsService


class McpToolService:
    fixed_speed_mps = 0.2
    command_interval_sec = 0.18
    prepared_voices: dict[str, dict[str, str]] = {
        "wake_ack": {"text": "我在", "description": "用户只是在呼唤小比时使用。"},
        "unknown": {"text": "不知道", "description": "用户要求超出当前能力范围时使用。"},
        "ok": {"text": "好的", "description": "已经收到用户请求时使用。"},
        "done": {"text": "已完成", "description": "动作或任务完成后使用。"},
    }

    def __init__(self, state: StateHub, adapter: CarAdapter, tts: TencentTtsService) -> None:
        self.state = state
        self.adapter = adapter
        self.tts = tts

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
            },
            {
                "name": "speak",
                "description": (
                    "Reply to the user by voice. Use mode='preset' whenever the intended reply can be covered "
                    "by one of the prepared voices; use mode='tts' only when a prepared voice is not suitable."
                ),
                "prepared_voices": self.prepared_voices,
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": ["preset", "tts"],
                            "description": "preset uses an existing prepared voice; tts creates a Tencent TTS task.",
                        },
                        "preset_key": {
                            "type": "string",
                            "enum": list(self.prepared_voices.keys()),
                            "description": "Required when mode is preset.",
                        },
                        "text": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 120,
                            "description": "Required when mode is tts; optional mirror text when mode is preset.",
                        },
                    },
                    "required": ["mode"],
                },
            },
            {
                "name": "speak_text",
                "description": "Compatibility wrapper: synthesize a short Chinese reply with Tencent TTS.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 120,
                            "description": "Short reply text to synthesize.",
                        }
                    },
                    "required": ["text"],
                },
            },
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

    async def speak(self, mode: str, text: str = "", preset_key: str = "") -> dict[str, Any]:
        normalized_mode = str(mode).lower().strip()
        normalized_text = str(text).strip()
        normalized_preset_key = str(preset_key).strip()

        if normalized_mode == "preset":
            voice = self.prepared_voices.get(normalized_preset_key)
            if not voice:
                raise ValueError("preset_key must reference a prepared voice")
            spoken_text = normalized_text or voice["text"]
            await self.state.add_report(
                title="Prepared voice selected",
                summary=f"Prepared voice selected: {normalized_preset_key} / {voice['text']}",
                details={
                    "tool": "speak",
                    "mode": "preset",
                    "preset_key": normalized_preset_key,
                    "text": spoken_text,
                    "prepared_text": voice["text"],
                    "description": voice["description"],
                },
            )
            return {
                "ok": True,
                "tool": "speak",
                "mode": "preset",
                "preset_key": normalized_preset_key,
                "text": spoken_text,
                "prepared_text": voice["text"],
            }

        if normalized_mode == "tts":
            result = await self.speak_text(normalized_text)
            result["tool"] = "speak"
            result["mode"] = "tts"
            return result

        raise ValueError("mode must be 'preset' or 'tts'")

    async def speak_text(self, text: str) -> dict[str, Any]:
        normalized_text = str(text).strip()
        if not normalized_text:
            raise ValueError("text must not be empty")

        task = await asyncio.to_thread(self.tts.submit_task, normalized_text, source="mcp_tool")
        await self.state.add_report(
            title="TTS synthesis task created",
            summary=f"Tencent TTS task submitted for: {normalized_text}",
            details={
                "tool": "speak_text",
                "task_id": task.get("task_id"),
                "text": normalized_text,
                "voice_type": task.get("voice_type"),
                "codec": task.get("codec"),
                "callback_url": task.get("callback_url"),
            },
        )
        return {
            "ok": True,
            "tool": "speak_text",
            "task_id": task.get("task_id"),
            "status": task.get("status_str"),
            "text": normalized_text,
            "callback_url": task.get("callback_url"),
        }
