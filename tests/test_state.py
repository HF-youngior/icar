from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import BACKEND  # noqa: F401

from tests.helpers import make_state


class StateHubTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state = make_state(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    async def test_confirm_alarm_updates_status_and_operator(self) -> None:
        alarm = await self.state.add_alarm("sensor_gas", "warning", "gas warning", "sensor")
        confirmed = await self.state.confirm_alarm(alarm["alarm_id"], "tester")

        self.assertIsNotNone(confirmed)
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(confirmed["confirmed_by"], "tester")
        self.assertIn("confirmed_at", confirmed)

    async def test_report_is_persisted_to_configured_directory(self) -> None:
        report = await self.state.add_report("到达厨房", "完成测试任务", {"point": "kitchen"})
        report_path = Path(self.tmp.name) / "reports" / f"{report['report_id']}.json"

        self.assertTrue(report_path.exists())
        self.assertIn("完成测试任务", report_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
