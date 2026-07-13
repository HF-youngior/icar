from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from tests import BACKEND  # noqa: F401

from app.vision import VisionService
from tests.helpers import make_config, make_state


class VisionServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmp.name)
        self.config = make_config(tmp_path)
        self.state = make_state(tmp_path)
        self.vision = VisionService(self.config, self.state)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    async def test_detect_once_respects_selected_targets(self) -> None:
        event = await self.vision.detect_once(["cat"])

        self.assertEqual(event["label"], "cat")
        self.assertEqual(event["source"], "camera_stream")
        self.assertEqual(event["target_filter"], ["cat"])

    async def test_start_and_stop_detection_updates_control_state(self) -> None:
        started = await self.vision.start_detection(["person", "cat"])

        self.assertTrue(started["running"])
        self.assertEqual(started["targets"], ["person", "cat"])
        self.assertEqual(self.state.snapshot()["vision_control"]["targets"], ["person", "cat"])

        stopped = await self.vision.stop_detection()

        self.assertFalse(stopped["running"])
        self.assertFalse(self.state.snapshot()["vision_control"]["running"])

    async def test_stop_detection_is_safe_when_not_running(self) -> None:
        stopped = await self.vision.stop_detection()
        await asyncio.sleep(0)

        self.assertFalse(stopped["running"])

    async def test_remote_detect_is_used_when_configured(self) -> None:
        self.config.vision.mode = "remote"
        self.config.vision.service_base_url = "http://127.0.0.1:8765"

        def fake_post_json(path: str, payload: dict[str, object]) -> dict[str, object]:
            self.assertEqual(path, "/detect")
            self.assertEqual(payload["targets"], ["dog"])
            return {
                "label": "dog",
                "label_zh": "宠物",
                "confidence": 0.91,
                "bbox": [10, 20, 30, 40],
                "source": "remote_yolo_stream",
            }

        self.vision._post_json = fake_post_json  # type: ignore[method-assign]

        event = await self.vision.detect_once(["dog"])

        self.assertEqual(event["label"], "dog")
        self.assertEqual(event["source"], "remote_yolo_stream")
        self.assertEqual(event["bbox"], [10, 20, 30, 40])

    async def test_remote_unknown_label_is_preserved(self) -> None:
        self.config.vision.mode = "remote"

        def fake_post_json(path: str, payload: dict[str, object]) -> dict[str, object]:
            return {
                "label": "traffic_light",
                "label_zh": "traffic_light",
                "confidence": 0.73,
                "bbox": [1, 2, 3, 4],
            }

        self.vision._post_json = fake_post_json  # type: ignore[method-assign]

        event = await self.vision.detect_once(["traffic_light"])

        self.assertEqual(event["label"], "traffic_light")
        self.assertEqual(event["label_zh"], "traffic_light")


if __name__ == "__main__":
    unittest.main()
