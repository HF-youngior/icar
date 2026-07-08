from __future__ import annotations

import asyncio
import math
from typing import Any

from ..config import CarConfig
from .base import CarAdapter


class Ros2CliCarAdapter(CarAdapter):
    name = "ros2_cli"

    def __init__(self, config: CarConfig) -> None:
        self.config = config

    async def connect(self) -> None:
        await self._run(["ros2", "topic", "list"])

    async def disconnect(self) -> None:
        return None

    async def _run(self, args: list[str]) -> dict[str, Any]:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.config.command_timeout_sec + 3)
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode("utf-8", errors="ignore") or "ros2 command failed")
        return {
            "ok": True,
            "adapter": self.name,
            "stdout": stdout.decode("utf-8", errors="ignore").strip(),
        }

    def _twist(self, direction: str, speed: float) -> str:
        linear = 0.0
        angular = 0.0
        if direction == "forward":
            linear = speed
        elif direction == "backward":
            linear = -speed
        elif direction == "left":
            angular = speed * 1.8
        elif direction == "right":
            angular = -speed * 1.8
        return "{linear: {x: %.3f, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: %.3f}}" % (linear, angular)

    async def manual_control(self, direction: str, speed: float) -> dict[str, Any]:
        return await self._run([
            "ros2",
            "topic",
            "pub",
            "--once",
            self.config.cmd_vel_topic,
            "geometry_msgs/msg/Twist",
            self._twist(direction, speed),
        ])

    async def stop(self) -> dict[str, Any]:
        return await self.manual_control("stop", 0.0)

    async def emergency_stop(self, reason: str = "web") -> dict[str, Any]:
        return await self.stop()

    async def send_navigation_goal(self, point: dict[str, Any]) -> dict[str, Any]:
        pose = point.get("pose", {})
        x = float(pose.get("x", 0))
        y = float(pose.get("y", 0))
        yaw = float(pose.get("theta", 0))
        z = math.sin(yaw / 2)
        w = math.cos(yaw / 2)
        goal = (
            "{header: {frame_id: 'map'}, pose: {position: {x: %.3f, y: %.3f, z: 0.0}, "
            "orientation: {x: 0.0, y: 0.0, z: %.6f, w: %.6f}}}"
        ) % (x, y, z, w)
        return await self._run([
            "ros2",
            "topic",
            "pub",
            "--once",
            self.config.nav_goal_topic,
            "geometry_msgs/msg/PoseStamped",
            goal,
        ])
