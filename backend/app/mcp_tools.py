from __future__ import annotations

import asyncio
import time
from typing import Any

from .adapters.base import CarAdapter
from .car_runtime import CarRuntimeRecovery
from .prepared_voice_assets import PreparedVoiceAssetService
from .state import StateHub
from .tts import TencentTtsService


class McpToolService:
    fixed_speed_mps = 0.2
    fixed_turn_speed = 0.16
    turn_degrees_per_pulse = 90
    turn_pulse_ms = 260
    turn_interval_ms = 300
    command_interval_sec = 0.30
    movement_start_retry_sec = 4.5
    movement_retry_interval_sec = 0.08
    prepared_voices: dict[str, dict[str, Any]] = {
        "wake_ack": {
            "text": "我在的，老大",
            "description": "用户只是在呼唤小比时使用。",
            "filename": "wake_ack.wav",
            "exposed_to_llm": True,
        },
        "unknown": {
            "text": "小比不会",
            "description": "用户要求超出当前能力范围时使用。",
            "filename": "unknown.wav",
            "exposed_to_llm": True,
        },
        "ok": {
            "text": "好的",
            "description": "已经收到用户请求时使用。",
            "filename": "ok.wav",
            "exposed_to_llm": True,
        },
        "done": {
            "text": "小比完成了",
            "description": "动作或任务完成后使用。",
            "filename": "done.wav",
            "exposed_to_llm": True,
        },
        "unreadable": {
            "text": "小比没有听清",
            "description": "当用户请求不能被理解时使用。",
            "filename": "unreadable.wav",
            "exposed_to_llm": True,
        },
        "low_battery": {
            "text": "小比电量有点低",
            "description": "小车或后端检测到低电量时主动播报。",
            "filename": "low_battery.wav",
            "exposed_to_llm": False,
        },
        "network_unstable": {
            "text": "小比网络好像不太稳定",
            "description": "连接腾讯云、DeepSeek 或小车通信失败时播报。",
            "filename": "network_unstable.wav",
            "exposed_to_llm": False,
        },
    }

    def __init__(self, state: StateHub, adapter: CarAdapter, tts: TencentTtsService, runtime: CarRuntimeRecovery) -> None:
        self.state = state
        self.adapter = adapter
        self.tts = tts
        self.runtime = runtime
        self.prepared_voice_assets = PreparedVoiceAssetService(runtime, self.prepared_voices)

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
                "name": "turn_degrees",
                "description": (
                    "Turn the car in place left or right. The LLM provides a desired angle in degrees; "
                    "the tool layer converts it into 90-degree turn pulses and sends low-level left/right commands."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "direction": {
                            "type": "string",
                            "enum": ["left", "right"],
                            "description": "Turn direction.",
                        },
                        "degrees": {
                            "type": "integer",
                            "enum": [90, 180, 270, 360],
                            "description": "Turn angle. Must be one of 90, 180, 270, or 360 degrees.",
                        },
                    },
                    "required": ["direction", "degrees"],
                },
            },
            {
                "name": "speak",
                "description": (
                    "Play a spoken reply on the car speaker. Use mode='preset' whenever the intended reply can be "
                    "covered by one of the prepared voices; use mode='tts' only when custom words are needed. "
                    "This tool should be used for verbal acknowledgements and spoken answers, not for buzzer cues."
                ),
                "prepared_voices": PreparedVoiceAssetService.llm_visible_voices(self.prepared_voices),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": ["preset", "tts"],
                            "description": "preset plays an existing prepared phrase; tts speaks custom text on the car.",
                        },
                        "preset_key": {
                            "type": "string",
                            "enum": list(PreparedVoiceAssetService.llm_visible_voices(self.prepared_voices).keys()),
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
                "name": "set_light",
                "description": (
                    "Turn the car's visible light on or off. Use this when the user asks for lights, visual "
                    "signalling, or a non-audio acknowledgement. This does not move the car and should not be "
                    "used as an emergency stop."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "enabled": {
                            "type": "boolean",
                            "description": "true turns the light on; false turns it off.",
                        },
                        "r": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 255,
                            "description": "Red channel for the light color when enabled.",
                        },
                        "g": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 255,
                            "description": "Green channel for the light color when enabled.",
                        },
                        "b": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 255,
                            "description": "Blue channel for the light color when enabled.",
                        },
                    },
                    "required": ["enabled"],
                },
            },
            {
                "name": "beep",
                "description": (
                    "Play a short buzzer cue on the car. Use this for brief confirmations, attention cues, "
                    "warnings, or helping the user locate the car. Do not use this for spoken replies; use "
                    "speak when words are needed."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "duration_ms": {
                            "type": "integer",
                            "minimum": 50,
                            "maximum": 2550,
                            "description": "How long the buzzer should sound, in milliseconds. Use 150-300ms for a normal acknowledgement.",
                        }
                    },
                    "required": [],
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
        requested_at = time.monotonic()
        movement_started_at: float | None = None
        sent_count = 0
        transient_errors: list[str] = []
        stop_result: dict[str, Any] | None = None

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
                now = time.monotonic()
                if movement_started_at is not None:
                    elapsed = now - movement_started_at
                    if elapsed >= duration_sec:
                        break
                elif now - requested_at >= self.movement_start_retry_sec:
                    break

                try:
                    await self.adapter.manual_control(direction, self.fixed_speed_mps)
                    sent_count += 1
                    if movement_started_at is None:
                        movement_started_at = time.monotonic()
                    remaining = duration_sec - (time.monotonic() - movement_started_at)
                    if remaining <= 0:
                        break
                    await asyncio.sleep(min(self.command_interval_sec, max(0.01, remaining)))
                except (OSError, TimeoutError, asyncio.TimeoutError) as exc:
                    transient_errors.append(str(exc) or exc.__class__.__name__)
                    await asyncio.sleep(self.movement_retry_interval_sec)

            if sent_count > 0:
                try:
                    stop_result = await self.adapter.stop()
                except (OSError, TimeoutError, asyncio.TimeoutError) as exc:
                    transient_errors.append(f"stop:{str(exc) or exc.__class__.__name__}")
        except Exception:
            await self.state.update_robot(speed=0, mode="offline")
            raise

        if sent_count <= 0:
            message = transient_errors[-1] if transient_errors else "no movement frame was sent"
            await self.state.update_robot(
                speed=0,
                mode="standby",
                target=None,
                last_command=f"move_distance:{direction}:not_sent",
                last_error=message,
            )
            await self.state.add_report(
                title=f"绉诲姩宸ュ叿 {direction}",
                summary="Move tool did not send a motion frame before the retry window ended.",
                details={
                    "tool": "move_distance",
                    "direction": direction,
                    "meters": meters,
                    "speed_mps": self.fixed_speed_mps,
                    "duration_sec": round(duration_sec, 3),
                    "sent_count": sent_count,
                    "errors": transient_errors[-5:],
                },
            )
            return {
                "ok": False,
                "tool": "move_distance",
                "direction": direction,
                "meters": meters,
                "speed_mps": self.fixed_speed_mps,
                "duration_sec": round(duration_sec, 3),
                "sent_count": sent_count,
                "transient": True,
                "message": message,
                "errors": transient_errors[-5:],
            }

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
                "sent_count": sent_count,
                "errors": transient_errors[-5:],
                "stop": stop_result,
            },
        )
        return {
            "ok": True,
            "tool": "move_distance",
            "direction": direction,
            "meters": meters,
            "speed_mps": self.fixed_speed_mps,
            "duration_sec": round(duration_sec, 3),
            "sent_count": sent_count,
            "errors": transient_errors[-5:],
            "stop": stop_result,
        }

    async def turn_degrees(self, direction: str, degrees: int) -> dict[str, Any]:
        direction = str(direction).lower().strip()
        degrees = int(degrees)
        if direction not in {"left", "right"}:
            raise ValueError("direction must be 'left' or 'right'")
        if degrees <= 0:
            raise ValueError("degrees must be greater than 0")
        if degrees % self.turn_degrees_per_pulse != 0:
            raise ValueError(f"degrees must be a multiple of {self.turn_degrees_per_pulse}")
        if degrees > 360:
            raise ValueError("degrees is too large for a single tool call")

        pulse_count = degrees // self.turn_degrees_per_pulse
        await self.state.update_robot(
            connected=True,
            mode="tool_turn",
            speed=self.fixed_turn_speed,
            target=f"{direction}:{degrees}deg",
            last_command=f"turn_degrees:{direction}:{degrees}",
            last_error=None,
        )

        try:
            for index in range(pulse_count):
                await self.adapter.manual_control(direction, self.fixed_turn_speed)
                await asyncio.sleep(self.turn_pulse_ms / 1000)
                await self.adapter.stop()
                if index < pulse_count - 1:
                    await asyncio.sleep(self.turn_interval_ms / 1000)
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
            title=f"转向工具 {direction}",
            summary=f"按 {self.turn_degrees_per_pulse} 度步进原地{('左' if direction == 'left' else '右')}转 {degrees} 度。",
            details={
                "tool": "turn_degrees",
                "direction": direction,
                "degrees": degrees,
                "degrees_per_pulse": self.turn_degrees_per_pulse,
                "pulse_count": pulse_count,
                "speed": self.fixed_turn_speed,
                "pulse_ms": self.turn_pulse_ms,
                "interval_ms": self.turn_interval_ms,
            },
        )
        return {
            "ok": True,
            "tool": "turn_degrees",
            "direction": direction,
            "degrees": degrees,
            "degrees_per_pulse": self.turn_degrees_per_pulse,
            "pulse_count": pulse_count,
            "speed": self.fixed_turn_speed,
            "pulse_ms": self.turn_pulse_ms,
            "interval_ms": self.turn_interval_ms,
        }

    async def speak(self, mode: str, text: str = "", preset_key: str = "") -> dict[str, Any]:
        normalized_mode = str(mode).lower().strip()
        normalized_text = str(text).strip()
        normalized_preset_key = str(preset_key).strip()

        if normalized_mode == "preset":
            voice = self.prepared_voices.get(normalized_preset_key)
            if not voice:
                raise ValueError("preset_key must reference a prepared voice")
            if not voice.get("exposed_to_llm", False):
                raise ValueError("preset_key is reserved for backend system use")
            spoken_text = str(voice["text"])
            playback = await self._play_prepared_voice(normalized_preset_key, spoken_text)
            await self.state.add_report(
                title="Prepared voice played on car",
                summary=f"Prepared voice played: {normalized_preset_key} / {spoken_text}",
                details={
                    "tool": "speak",
                    "mode": "preset",
                    "preset_key": normalized_preset_key,
                    "text": spoken_text,
                    "prepared_text": voice["text"],
                    "description": voice["description"],
                    "playback": playback,
                },
            )
            return {
                "ok": playback.get("ok", False),
                "tool": "speak",
                "mode": "preset",
                "preset_key": normalized_preset_key,
                "text": spoken_text,
                "prepared_text": voice["text"],
                "playback": playback,
            }

        if normalized_mode == "tts":
            if not normalized_text:
                raise ValueError("text must not be empty when mode is tts")
            playback = await self._play_voice(normalized_text)
            await self.state.add_report(
                title="Custom voice played on car",
                summary=f"Car voice requested: {normalized_text}",
                details={
                    "tool": "speak",
                    "mode": "tts",
                    "text": normalized_text,
                    "playback": playback,
                },
            )
            return {
                "ok": playback.get("ok", False),
                "tool": "speak",
                "mode": "tts",
                "text": normalized_text,
                "playback": playback,
            }

        raise ValueError("mode must be 'preset' or 'tts'")

    async def set_light(self, enabled: bool, r: int = 38, g: int = 244, b: int = 255) -> dict[str, Any]:
        is_enabled = self._bool_value(enabled)
        red = self._clamp_byte(r if is_enabled else 0)
        green = self._clamp_byte(g if is_enabled else 0)
        blue = self._clamp_byte(b if is_enabled else 0)

        if self.adapter.name == "tcp":
            runtime_result = await asyncio.to_thread(
                self.runtime.control_light,
                enabled=is_enabled,
                r=red,
                g=green,
                b=blue,
            )
            tcp_result = await self.adapter.auxiliary_control(
                "light",
                enabled=is_enabled,
                r=red,
                g=green,
                b=blue,
            )
            result: dict[str, Any] = {
                "ok": bool(runtime_result.get("ok")) or bool(tcp_result.get("ok")),
                "tool": "set_light",
                "adapter": "ssh-rosmaster+tcp",
                "enabled": is_enabled,
                "rgb": [red, green, blue],
                "runtime": runtime_result,
                "tcp": tcp_result,
            }
            if not result["ok"]:
                result["warning"] = "light command was sent through all known paths, but no path confirmed delivery"
        else:
            adapter_result = await self.adapter.auxiliary_control(
                "light",
                enabled=is_enabled,
                r=red,
                g=green,
                b=blue,
            )
            result = {
                "ok": adapter_result.get("ok", False),
                "tool": "set_light",
                "enabled": is_enabled,
                "rgb": [red, green, blue],
                "adapter_result": adapter_result,
            }

        await self.state.update_robot(connected=True, last_command="aux:light", last_error=None)
        await self.state.add_report(
            title="Light command sent",
            summary=f"Car light {'on' if is_enabled else 'off'}",
            details=result,
        )
        return result

    async def beep(self, duration_ms: int = 260) -> dict[str, Any]:
        duration = max(50, min(2550, int(duration_ms or 260)))
        adapter_result = await self.adapter.auxiliary_control("buzzer", duration_ms=duration)
        result = {
            "ok": adapter_result.get("ok", False),
            "tool": "beep",
            "duration_ms": duration,
            "adapter_result": adapter_result,
        }
        await self.state.update_robot(connected=True, last_command="aux:buzzer", last_error=None)
        await self.state.add_report(
            title="Buzzer cue sent",
            summary=f"Car buzzer cue sent for {duration} ms",
            details=result,
        )
        return result

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

    async def _play_voice(self, text: str) -> dict[str, Any]:
        if self.adapter.name == "tcp":
            return await asyncio.to_thread(self.runtime.play_voice, text=text)
        return await self.adapter.auxiliary_control("voice", text=text, volume_percent=85)

    async def _play_prepared_voice(self, preset_key: str, fallback_text: str) -> dict[str, Any]:
        if self.adapter.name == "tcp":
            playback = await asyncio.to_thread(self.prepared_voice_assets.play_prepared, preset_key)
            if playback.get("ok"):
                return playback
        fallback = await self._play_voice(fallback_text)
        fallback["prepared_voice_fallback"] = True
        return fallback

    async def sync_prepared_voices(self) -> dict[str, Any]:
        if self.adapter.name != "tcp":
            return {"ok": True, "skipped": True, "reason": "prepared voice sync only runs for tcp/ssh car adapter"}
        return await asyncio.to_thread(self.prepared_voice_assets.ensure_synced)

    def _clamp_byte(self, value: Any) -> int:
        return max(0, min(255, int(value)))

    def _bool_value(self, value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
        return bool(value)
