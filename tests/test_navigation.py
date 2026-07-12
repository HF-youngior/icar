from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests import BACKEND  # noqa: F401

from app.adapters.base import CarAdapter
from app.navigation import NavigationService

from tests.helpers import make_state


class FakeAdapter(CarAdapter):
    name = "fake"

    def __init__(self) -> None:
        self.goals: list[str] = []
        self.stopped = False
        self.emergency_reason: str | None = None

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def manual_control(self, direction: str, speed: float) -> dict[str, Any]:
        return {"ok": True, "direction": direction, "speed": speed}

    async def stop(self) -> dict[str, Any]:
        self.stopped = True
        return {"ok": True}

    async def emergency_stop(self, reason: str = "web") -> dict[str, Any]:
        self.emergency_reason = reason
        return {"ok": True}

    async def send_navigation_goal(self, point: dict[str, Any]) -> dict[str, Any]:
        self.goals.append(str(point["id"]))
        return {"ok": True}


class NavigationServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.points = [
            {"id": "living_room", "name": "客厅", "pose": {"x": 1, "y": 1, "theta": 0}},
            {"id": "kitchen", "name": "厨房", "pose": {"x": 4, "y": 1, "theta": 1.57}},
        ]
        self.routes = [{"id": "home", "name": "全屋巡逻", "points": ["living_room", "kitchen"]}]
        self.state = make_state(Path(self.tmp.name), points=self.points, routes=self.routes)
        self.adapter = FakeAdapter()
        self.service = NavigationService(self.state.config, self.state, self.adapter)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    async def test_go_to_starts_navigation_task(self) -> None:
        nav = await self.service.go_to("kitchen")

        self.assertEqual(nav["state"], "running")
        self.assertEqual(nav["target"]["id"], "kitchen")
        self.assertEqual(self.state.robot["mode"], "navigation")
        self.assertEqual(self.adapter.goals, ["kitchen"])

    async def test_arriving_at_single_target_creates_report(self) -> None:
        await self.service.go_to("kitchen")
        await self.state.update_navigation(progress=1)
        await self.service._simulate_progress()

        self.assertEqual(self.state.navigation["state"], "arrived")
        self.assertEqual(self.state.robot["mode"], "standby")
        self.assertEqual(len(self.state.reports), 1)

    async def test_patrol_advances_to_next_point_then_completes(self) -> None:
        await self.service.start_patrol("home")
        await self.state.update_navigation(progress=1)
        await self.service._simulate_progress()

        self.assertEqual(self.state.navigation["state"], "running")
        self.assertEqual(self.state.navigation["target"]["id"], "kitchen")
        self.assertEqual(self.adapter.goals, ["living_room", "kitchen"])

        await self.state.update_navigation(progress=1)
        await self.service._simulate_progress()

        self.assertEqual(self.state.navigation["state"], "completed")
        self.assertEqual(self.state.robot["mode"], "standby")

    async def test_emergency_stop_updates_state_and_alarm(self) -> None:
        await self.service.emergency_stop("test")

        self.assertEqual(self.state.navigation["state"], "emergency_stop")
        self.assertEqual(self.state.robot["mode"], "emergency_stop")
        self.assertEqual(self.adapter.emergency_reason, "test")
        self.assertEqual(self.state.alarms[0]["type"], "emergency_stop")


if __name__ == "__main__":
    unittest.main()
