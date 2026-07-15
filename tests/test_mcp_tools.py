from __future__ import annotations

import unittest
from typing import Any

from tests import BACKEND  # noqa: F401

from app.mcp_tools import McpToolService


class DummyState:
    def __init__(self) -> None:
        self.robot_updates: list[dict[str, Any]] = []
        self.reports: list[dict[str, Any]] = []

    async def update_robot(self, **values: Any) -> None:
        self.robot_updates.append(values)

    async def add_report(self, title: str, summary: str, details: dict[str, Any]) -> None:
        self.reports.append({"title": title, "summary": summary, "details": details})


class FlakyAdapter:
    name = "tcp"

    def __init__(self, failures_before_success: int) -> None:
        self.failures_before_success = failures_before_success
        self.manual_calls = 0
        self.stop_calls = 0

    async def manual_control(self, direction: str, speed: float) -> dict[str, Any]:
        self.manual_calls += 1
        if self.manual_calls <= self.failures_before_success:
            raise TimeoutError("simulated timeout")
        return {"ok": True, "direction": direction, "speed": speed}

    async def stop(self) -> dict[str, Any]:
        self.stop_calls += 1
        return {"ok": True, "direction": "stop"}


class McpToolServiceTest(unittest.IsolatedAsyncioTestCase):
    def make_service(self, adapter: FlakyAdapter) -> McpToolService:
        service = McpToolService(DummyState(), adapter, tts=None, runtime=None)  # type: ignore[arg-type]
        service.fixed_speed_mps = 1.0
        service.command_interval_sec = 0.03
        service.movement_start_retry_sec = 0.12
        service.movement_retry_interval_sec = 0.01
        return service

    async def test_move_distance_retries_transient_timeout(self) -> None:
        adapter = FlakyAdapter(failures_before_success=1)
        service = self.make_service(adapter)

        result = await service.move_distance("forward", 0.05)

        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["sent_count"], 1)
        self.assertEqual(adapter.stop_calls, 1)
        self.assertEqual(result["errors"], ["simulated timeout"])

    async def test_move_distance_returns_transient_failure_when_no_frame_sent(self) -> None:
        adapter = FlakyAdapter(failures_before_success=100)
        service = self.make_service(adapter)

        result = await service.move_distance("backward", 0.05)

        self.assertFalse(result["ok"])
        self.assertTrue(result["transient"])
        self.assertEqual(result["sent_count"], 0)
        self.assertEqual(adapter.stop_calls, 0)


if __name__ == "__main__":
    unittest.main()
