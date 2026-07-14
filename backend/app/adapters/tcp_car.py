from __future__ import annotations

import asyncio
from typing import Any

from ..config import CarConfig
from .base import CarAdapter


class TcpCarAdapter(CarAdapter):
    name = "tcp"
    max_ui_speed_mps = 0.32

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

    async def _send_payload(self, payload: str) -> None:
        await self._send_payload_with_timeout(payload, self.config.command_timeout_sec)

    async def _send_payload_with_timeout(self, payload: str, timeout_sec: float) -> None:
        data = payload.encode("utf-8")
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.config.host, self.config.port),
            timeout=timeout_sec,
        )
        writer.write(data)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def _send_payloads(
        self,
        key: str,
        payloads: list[str],
        *,
        tolerate_errors: bool = False,
        timeout_sec: float | None = None,
        **values: Any,
    ) -> dict[str, Any]:
        errors: list[str] = []
        sent_frames: list[str] = []
        timeout = timeout_sec or self.config.command_timeout_sec
        for index, payload in enumerate(payloads):
            try:
                await self._send_payload_with_timeout(payload, timeout)
                sent_frames.append(payload)
            except (OSError, TimeoutError, asyncio.TimeoutError) as exc:
                errors.append(str(exc) or exc.__class__.__name__)
                if not tolerate_errors:
                    raise
            if index < len(payloads) - 1:
                await asyncio.sleep(0.05)
        result = {
            "ok": not errors or bool(sent_frames),
            "adapter": self.name,
            "command": key,
            "frames": payloads,
            "sent_frames": sent_frames,
            "bytes": sum(len(payload.encode("utf-8")) for payload in payloads),
        }
        if errors:
            result["errors"] = errors
        result.update(values)
        return result

    async def _send(self, key: str, **values: Any) -> dict[str, Any]:
        payloads = self._command_payloads(key, **values)
        return await self._send_payloads(key, payloads)

    def _command_payloads(self, key: str, **values: Any) -> list[str]:
        direction_map = {
            "stop": 0,
            "forward": 1,
            "backward": 2,
            "emergency_stop": 7,
        }
        if self.config.port == 6000:
            direction_map.update({
                "left": 5,
                "right": 6,
            })
        else:
            direction_map.update({
                "left": 6,
                "right": 5,
            })
        if key not in direction_map:
            raise ValueError(f"Unsupported TCP command: {key}")
        movement = self._encode_frame("15", self._hex(direction_map[key]))
        if key == "emergency_stop":
            return [self._encode_frame("15", "00")]
        if key == "stop":
            return [movement]
        speed = float(values.get("speed", 0.16))
        return [self._encode_speed_frame(speed), movement]

    def _encode_frame(self, command: str, info: str = "") -> str:
        size = self._hex(len(info) + 2)
        body = f"01{command}{size}{info}"
        return self._wrap_body(body)

    def _encode_raw_frame(self, values: list[int]) -> str:
        return self._wrap_body("".join(self._hex(value) for value in values))

    def _encode_speed_frame(self, speed: float) -> str:
        percent = self._speed_percent(speed)
        return self._encode_raw_frame([0x01, 0x16, 0x06, percent, percent])

    def _wrap_body(self, body: str) -> str:
        checksum = 0
        for index in range(0, len(body), 2):
            checksum = (checksum + int(body[index:index + 2], 16)) % 256
        return f"${body}{self._hex(checksum)}#"

    def _speed_percent(self, speed: float) -> int:
        if speed <= 1:
            percent = round((max(0.0, speed) / self.max_ui_speed_mps) * 100)
        else:
            percent = round(speed)
        return max(0, min(100, percent))

    def _hex(self, value: int, width: int = 2) -> str:
        return f"{value:0{width}X}"

    async def manual_control(self, direction: str, speed: float) -> dict[str, Any]:
        return await self._send(direction, speed=speed)

    async def stop(self) -> dict[str, Any]:
        stop_frame = self._command_payloads("stop")[0]
        return await self._send_payloads("stop", [stop_frame], tolerate_errors=True, timeout_sec=0.8)

    async def emergency_stop(self, reason: str = "web") -> dict[str, Any]:
        stop_frame = self._command_payloads("stop")[0]
        return await self._send_payloads(
            "emergency_stop",
            [stop_frame, stop_frame, stop_frame, stop_frame, stop_frame],
            tolerate_errors=True,
            timeout_sec=0.8,
            reason=reason,
        )

    async def send_navigation_goal(self, point: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("TCP navigation needs the car protocol from the course material.")

    async def auxiliary_control(self, action: str, **values: Any) -> dict[str, Any]:
        payloads = self._auxiliary_payloads(action, **values)
        result = await self._send_payloads(action, payloads, tolerate_errors=True, timeout_sec=1.0)
        result["action"] = action
        return result

    def _auxiliary_payloads(self, action: str, **values: Any) -> list[str]:
        if action == "light":
            return self._light_payloads(**values)
        return [self._auxiliary_payload(action, **values)]

    def _light_payloads(self, **values: Any) -> list[str]:
        enabled = self._bool_value(values.get("enabled", False))
        red = int(values.get("r", 38 if enabled else 0))
        green = int(values.get("g", 244 if enabled else 0))
        blue = int(values.get("b", 255 if enabled else 0))
        rgb = [max(0, min(255, value)) for value in (red, green, blue)]
        led_ids = values.get("led_ids") or [0, 1, 2, 3, 4]
        left_light = 1 if enabled else 0
        right_light = 1 if enabled else 0
        duration_ms = max(0, min(65535, int(values.get("duration_ms", 0))))
        duration_low = duration_ms & 0xFF
        duration_high = (duration_ms >> 8) & 0xFF

        # Teacher-provided iCAR firmware uses FUNC_RGB=0x05 for the
        # physical left/right headlights: left, right, duration low/high.
        # Keep RGB/App-compatible frames after it as fallbacks for other
        # car images.
        payloads = [
            self._encode_raw_frame([car_type, 0x05, 0x08, left_light, right_light, duration_low, duration_high])
            for car_type in (0x00, 0x01)
        ]

        payloads.extend(
            self._encode_raw_frame([0x03, 0x20, 0x08, int(led_id), *rgb])
            for led_id in led_ids
        )
        payloads.extend(
            self._encode_raw_frame([0x01, 0x30, 0x08, int(led_id), *rgb])
            for led_id in led_ids
        )
        return payloads

    def _auxiliary_payload(self, action: str, **values: Any) -> str:
        if action == "follow_line":
            enabled = self._bool_value(values.get("enabled", False))
            return self._encode_raw_frame([0x01, 0x63 if enabled else 0x64, 0x02])
        if action == "buzzer":
            duration_ms = max(0, min(2550, int(values.get("duration_ms", 300))))
            delay = max(0, min(255, round(duration_ms / 10)))
            return self._encode_raw_frame([0x01, 0x13, 0x06, 0x01 if duration_ms else 0x00, delay])
        if action == "light":
            return self._light_payloads(**values)[0]
        raise ValueError(f"Unsupported auxiliary TCP command: {action}")

    def _bool_value(self, value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
        return bool(value)
