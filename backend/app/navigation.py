from __future__ import annotations

import asyncio
import math
import uuid
from typing import Any

from .adapters.base import CarAdapter
from .config import AppConfig
from .state import StateHub, now_text


class NavigationService:
    def __init__(self, config: AppConfig, state: StateHub, adapter: CarAdapter) -> None:
        self.config = config
        self.state = state
        self.adapter = adapter
        self._task: asyncio.Task[None] | None = None

    def start_background(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def go_to(self, point_id: str) -> dict[str, Any]:
        point = self.state.point_by_id(point_id)
        if not point:
            raise ValueError(f"Unknown point: {point_id}")
        task_id = f"nav-{uuid.uuid4().hex[:8]}"
        await self.adapter.send_navigation_goal(point)
        await self.state.update_navigation(
            task_id=task_id,
            state="running",
            target=point,
            route=[],
            route_index=0,
            progress=0,
            message=f"正在前往{point.get('name', point_id)}",
            started_at=now_text(),
        )
        await self.state.update_robot(mode="navigation", target=point.get("name"), speed=0.18)
        return self.state.navigation

    async def start_patrol(self, route_id: str) -> dict[str, Any]:
        route = self.state.route_by_id(route_id)
        if not route:
            raise ValueError(f"Unknown route: {route_id}")
        point_ids = route.get("points", [])
        if not point_ids:
            raise ValueError("Route has no points")
        task_id = f"patrol-{uuid.uuid4().hex[:8]}"
        first_point = self.state.point_by_id(point_ids[0])
        if not first_point:
            raise ValueError(f"Route point not found: {point_ids[0]}")
        await self.adapter.send_navigation_goal(first_point)
        await self.state.update_navigation(
            task_id=task_id,
            state="running",
            target=first_point,
            route=point_ids,
            route_index=0,
            progress=0,
            message=f"巡逻路线：{route.get('name')}",
            started_at=now_text(),
        )
        await self.state.update_robot(mode="patrol", target=first_point.get("name"), speed=0.16)
        return self.state.navigation

    async def stop(self, state: str = "stopped", message: str = "任务已停止") -> None:
        await self.adapter.stop()
        await self.state.update_navigation(state=state, progress=0, message=message)
        await self.state.update_robot(mode="standby", speed=0, target=None)

    async def emergency_stop(self, reason: str = "web") -> None:
        await self.adapter.emergency_stop(reason)
        await self.state.update_navigation(state="emergency_stop", message=f"急停：{reason}", progress=0)
        await self.state.update_robot(mode="emergency_stop", speed=0, target=None, last_command="emergency_stop")
        await self.state.add_alarm("emergency_stop", "danger", f"急停触发：{reason}", "navigation")

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.navigation_tick_sec)
            if self.config.car.adapter != "simulated":
                continue
            nav = self.state.navigation
            if nav.get("state") != "running" or not nav.get("target"):
                continue
            await self._simulate_progress()

    async def _simulate_progress(self) -> None:
        nav = self.state.navigation
        target = nav["target"]
        progress = min(1.0, float(nav.get("progress", 0)) + 0.055)
        current_pose = self.state.robot.get("pose", {"x": 0, "y": 0, "theta": 0})
        target_pose = target.get("pose", {})
        pose = self._interpolate_pose(current_pose, target_pose, progress)
        await self.state.update_robot(pose=pose, speed=0.16 if progress < 1 else 0)
        if progress < 1:
            await self.state.update_navigation(progress=round(progress, 3), message=f"正在前往{target.get('name')}")
            return

        await self._arrive_current_target()

    def _interpolate_pose(self, current: dict[str, Any], target: dict[str, Any], progress: float) -> dict[str, float]:
        tx = float(target.get("x", current.get("x", 0)))
        ty = float(target.get("y", current.get("y", 0)))
        cx = float(current.get("x", 0))
        cy = float(current.get("y", 0))
        step = min(0.22, max(0.02, progress))
        return {
            "x": round(cx + (tx - cx) * step, 3),
            "y": round(cy + (ty - cy) * step, 3),
            "theta": round(float(target.get("theta", math.atan2(ty - cy, tx - cx))), 3),
        }

    async def _arrive_current_target(self) -> None:
        nav = self.state.navigation
        target = nav.get("target") or {}
        route = nav.get("route") or []
        route_index = int(nav.get("route_index") or 0)
        await self.state.add_report(
            title=f"到达{target.get('name', '目标点')}",
            summary=f"机器人已到达{target.get('name', '目标点')}，完成一次点位任务。",
            details={"navigation": nav, "sensors": list(self.state.sensors.values())},
        )

        if route and route_index + 1 < len(route):
            next_index = route_index + 1
            next_point = self.state.point_by_id(route[next_index])
            if next_point:
                await self.adapter.send_navigation_goal(next_point)
                await self.state.update_navigation(
                    route_index=next_index,
                    target=next_point,
                    progress=0,
                    message=f"继续巡逻：{next_point.get('name')}",
                )
                await self.state.update_robot(mode="patrol", target=next_point.get("name"), speed=0.16)
                return

        finished_state = "arrived" if not route else "completed"
        await self.state.update_navigation(
            state=finished_state,
            progress=1,
            message="导航任务完成" if not route else "巡逻路线完成",
        )
        await self.state.update_robot(mode="standby", speed=0, target=None)

