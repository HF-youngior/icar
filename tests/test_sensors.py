from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import BACKEND  # noqa: F401

from app.sensors import SensorService

from tests.helpers import make_state


class SensorServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state = make_state(Path(self.tmp.name))
        self.service = SensorService(self.state.config, self.state)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_level_thresholds(self) -> None:
        self.assertEqual(self.service._level("temperature", 24), "normal")
        self.assertEqual(self.service._level("temperature", 30), "warning")
        self.assertEqual(self.service._level("temperature", 36), "danger")
        self.assertEqual(self.service._level("light", 91), "normal")
        self.assertEqual(self.service._level("light", 90), "warning")
        self.assertEqual(self.service._level("light", 40), "danger")

    async def test_alarm_is_deduplicated_until_sensor_returns_normal(self) -> None:
        await self.service._maybe_alarm("gas", 0.4, "warning")
        await self.service._maybe_alarm("gas", 0.42, "warning")
        self.assertEqual(len(self.state.alarms), 1)

        await self.service._maybe_alarm("gas", 0.08, "normal")
        await self.service._maybe_alarm("gas", 0.41, "warning")
        self.assertEqual(len(self.state.alarms), 2)


if __name__ == "__main__":
    unittest.main()
