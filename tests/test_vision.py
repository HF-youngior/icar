from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from tests import BACKEND  # noqa: F401

from app.hazard_vision import _MjpegReader
from app.vision import VisionService
from tests.helpers import make_config, make_state


class VisionServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmp.name)
        self.config = make_config(tmp_path)
        self.config.vision.mode = "simulated"
        self.state = make_state(tmp_path)
        self.state.config.vision.mode = "simulated"
        self.vision = VisionService(self.config, self.state)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    async def test_detect_once_respects_selected_targets(self) -> None:
        event = await self.vision.detect_once(["cat"], "search")

        self.assertEqual(event["label"], "cat")
        self.assertEqual(event["source"], "camera_stream")
        self.assertEqual(event["target_filter"], ["cat"])

    async def test_start_and_stop_detection_updates_control_state(self) -> None:
        started = await self.vision.start_detection(["person", "cat"], "search")

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

    async def test_available_modes_do_not_include_unimplemented_patrol(self) -> None:
        mode_ids = [mode["id"] for mode in self.vision.available_modes()]

        self.assertEqual(mode_ids, ["normal", "travel", "care", "hazard", "search"])
        self.assertEqual(self.vision._normalize_mode("patrol"), "normal")

    async def test_remote_detect_is_used_when_configured(self) -> None:
        self.config.vision.mode = "remote"
        self.config.vision.service_base_url = "http://127.0.0.1:8765"

        def fake_get_json(path: str) -> dict[str, object]:
            return {"targets": [{"id": "dog", "label": "dog", "label_zh": "宠物"}]}

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

        self.vision._get_json = fake_get_json  # type: ignore[method-assign]
        self.vision._post_json = fake_post_json  # type: ignore[method-assign]

        event = await self.vision.detect_once(["dog"], "search")

        self.assertEqual(event["label"], "dog")
        self.assertEqual(event["source"], "remote_yolo_stream")
        self.assertEqual(event["bbox"], [10, 20, 30, 40])

    async def test_remote_unknown_label_is_preserved(self) -> None:
        self.config.vision.mode = "remote"

        def fake_get_json(path: str) -> dict[str, object]:
            return {"targets": [{"id": "traffic_light", "label": "traffic_light", "label_zh": "traffic_light"}]}

        def fake_post_json(path: str, payload: dict[str, object]) -> dict[str, object]:
            return {
                "label": "traffic_light",
                "label_zh": "traffic_light",
                "confidence": 0.73,
                "bbox": [1, 2, 3, 4],
            }

        self.vision._get_json = fake_get_json  # type: ignore[method-assign]
        self.vision._post_json = fake_post_json  # type: ignore[method-assign]

        event = await self.vision.detect_once(["traffic_light"], "search")

        self.assertEqual(event["label"], "traffic_light")
        self.assertEqual(event["label_zh"], "traffic_light")

    async def test_backend_yolo_is_used_before_remote_yolo_when_enabled(self) -> None:
        class FakeObjectDetector:
            @property
            def available(self) -> bool:
                return True

            def status(self) -> dict[str, object]:
                return {"enabled": True, "available": True}

            def available_targets(self) -> list[dict[str, str]]:
                return [{"id": "person", "label": "person", "label_zh": "person"}]

            def detect(self, stream_url: str, targets: list[str]) -> dict[str, object]:
                return {
                    "label": "person",
                    "label_zh": "person",
                    "confidence": 0.94,
                    "bbox": [10, 20, 110, 180],
                    "source": "backend_yolov5s",
                    "metadata": {
                        "detections": [
                            {"label": "person", "confidence": 0.94, "bbox": [10, 20, 110, 180]},
                        ],
                    },
                }

        def fake_post_json(path: str, payload: dict[str, object]) -> dict[str, object]:
            raise AssertionError("backend YOLO should be used before remote YOLO")

        self.config.vision.mode = "remote"
        self.vision.object_detector = FakeObjectDetector()  # type: ignore[assignment]
        self.vision._post_json = fake_post_json  # type: ignore[method-assign]

        event = await self.vision.detect_once(["person"], "search")

        self.assertEqual(event["label"], "person")
        self.assertEqual(event["source"], "backend_yolov5s")
        self.assertEqual(event["target_filter"], ["person"])
        self.assertEqual(self.vision.available_targets()[0]["id"], "person")
        self.assertTrue(self.vision.status()["backend_yolo"]["available"])

    async def test_remote_mode_does_not_fallback_when_health_fails(self) -> None:
        self.config.vision.mode = "remote"

        def fake_get_json(path: str) -> dict[str, object]:
            raise TimeoutError("health unavailable")

        self.vision._get_json = fake_get_json  # type: ignore[method-assign]

        self.assertEqual(self.vision.available_targets(), [])
        self.assertEqual(self.vision._normalize_targets(["person"], "travel"), ["person", "smoke", "fire"])
        self.assertEqual(self.vision._normalize_targets(["person"], "hazard"), ["smoke", "fire"])
        self.assertEqual(self.vision._normalize_targets(["person"], "normal"), [])

    async def test_auto_mode_without_yolo_returns_clear_not_simulated_detection(self) -> None:
        self.config.vision.mode = "auto"

        def fake_post_json(path: str, payload: dict[str, object]) -> dict[str, object]:
            raise TimeoutError("remote yolo unavailable")

        self.vision._post_json = fake_post_json  # type: ignore[method-assign]

        event = await self.vision.detect_once(["person"], "normal")

        self.assertEqual(event["label"], "clear")
        self.assertEqual(event["confidence"], 0.0)
        self.assertEqual(event["bbox"], [0, 0, 0, 0])
        self.assertEqual(event["source"], "vision_unavailable")
        self.assertIn("error", event["metadata"])

    async def test_normal_mode_records_event_without_alarm(self) -> None:
        event = await self.vision.detect_once(["person"], "normal")

        self.assertEqual(event["label"], "person")
        self.assertEqual(event["target_filter"], [])
        self.assertEqual(len(self.state.vision), 1)
        self.assertEqual(self.state.alarms, [])

    async def test_travel_mode_alarms_on_person(self) -> None:
        event = await self.vision.detect_once(["person"], "travel")

        self.assertEqual(event["label"], "person")
        self.assertEqual(event["target_filter"], ["person", "smoke", "fire"])
        self.assertEqual(len(self.state.alarms), 1)
        self.assertEqual(self.state.alarms[0]["type"], "vision_person_travel")
        self.assertEqual(self.state.alarms[0]["metadata"]["vision_mode"], "travel")
        self.assertEqual(self.state.alarms[0]["metadata"]["vision_mode_label"], "旅游安防模式")

    async def test_travel_mode_continuous_person_alarm_is_not_missed_or_duplicated(self) -> None:
        self.config.vision.mode = "remote"

        def fake_post_json(path: str, payload: dict[str, object]) -> dict[str, object]:
            return {
                "label": "person",
                "label_zh": "人员",
                "confidence": 0.9,
                "bbox": [20, 40, 120, 240],
                "metadata": {
                    "detections": [
                        [70, 140, 0, "person", 0.9, [20, 40, 120, 240]],
                    ],
                },
            }

        self.vision._post_json = fake_post_json  # type: ignore[method-assign]

        await self.vision.detect_changed_once(None, "travel")
        await self.vision.detect_changed_once(None, "travel")

        person_alarms = [alarm for alarm in self.state.alarms if alarm["type"] == "vision_person_travel"]
        self.assertEqual(len(person_alarms), 1)
        self.assertEqual(len(self.state.vision), 1)

    async def test_care_mode_confirms_fall_after_consecutive_person_height_drop(self) -> None:
        self.config.vision.mode = "remote"
        buzzer_calls: list[tuple[str, dict[str, object]]] = []
        boxes = [
            [120, 20, 220, 320],
            [120, 190, 240, 320],
            [120, 190, 240, 320],
            [120, 190, 240, 320],
        ]

        def fake_post_json(path: str, payload: dict[str, object]) -> dict[str, object]:
            self.assertEqual(payload["targets"], ["person", "smoke", "fire"])
            bbox = boxes.pop(0)
            return {
                "label": "person",
                "label_zh": "人员",
                "confidence": 0.9,
                "bbox": bbox,
                "metadata": {
                    "detections": [
                        [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2, 0, "person", 0.9, bbox],
                    ],
                },
            }

        self.vision._post_json = fake_post_json  # type: ignore[method-assign]

        async def fake_auxiliary(action: str, values: dict[str, object]) -> None:
            buzzer_calls.append((action, values))

        self.vision.auxiliary_callback = fake_auxiliary

        await self.vision.detect_changed_once(None, "care")
        await self.vision.detect_changed_once(None, "care")
        await self.vision.detect_changed_once(None, "care")
        await self.vision.detect_changed_once(None, "care")

        fall_alarms = [alarm for alarm in self.state.alarms if alarm["type"] == "vision_fall"]
        self.assertEqual(len(fall_alarms), 1)
        self.assertEqual(fall_alarms[0]["level"], "danger")
        self.assertEqual(fall_alarms[0]["metadata"]["vision_mode"], "care")
        self.assertTrue(fall_alarms[0]["metadata"]["fall_rule"]["requires_height_drop"])
        self.assertEqual(fall_alarms[0]["metadata"]["fall_rule"]["baseline_height"], 300)
        self.assertEqual(fall_alarms[0]["metadata"]["fall_rule"]["current_height"], 130)
        self.assertEqual([call[0] for call in buzzer_calls], ["buzzer", "buzzer"])
        self.assertEqual(buzzer_calls[0][1]["duration_ms"], 160)

    async def test_care_mode_does_not_alarm_when_person_is_already_lying_down(self) -> None:
        self.config.vision.mode = "remote"

        def fake_post_json(path: str, payload: dict[str, object]) -> dict[str, object]:
            bbox = [120, 190, 240, 320]
            return {
                "label": "person",
                "label_zh": "人员",
                "confidence": 0.9,
                "bbox": bbox,
                "metadata": {
                    "detections": [
                        [160, 185, 0, "person", 0.9, bbox],
                    ],
                },
            }

        self.vision._post_json = fake_post_json  # type: ignore[method-assign]

        await self.vision.detect_changed_once(None, "care")
        await self.vision.detect_changed_once(None, "care")
        await self.vision.detect_changed_once(None, "care")
        await self.vision.detect_changed_once(None, "care")

        fall_alarms = [alarm for alarm in self.state.alarms if alarm["type"] == "vision_fall"]
        self.assertEqual(fall_alarms, [])

    async def test_security_modes_alarm_on_smoke_or_fire_labels(self) -> None:
        event = {
            "label": "smoke",
            "label_zh": "烟雾",
            "confidence": 0.86,
            "bbox": [10, 20, 120, 160],
            "source": "remote_yolo_stream",
            "target_filter": ["person", "smoke", "fire"],
            "mode": "travel",
        }

        await self.vision._record_detection_event(event)

        self.assertEqual(self.state.alarms[0]["type"], "vision_smoke")
        self.assertEqual(self.state.alarms[0]["level"], "danger")
        self.assertEqual(self.state.alarms[0]["metadata"]["hazard"], "smoke")

    async def test_backend_hazard_detector_records_smoke_event_and_alarm(self) -> None:
        class FakeHazardDetector:
            def status(self) -> dict[str, object]:
                return {"enabled": True, "available": True}

            def detect(self, stream_url: str) -> dict[str, object]:
                return {
                    "label": "fire",
                    "label_zh": "火灾",
                    "confidence": 0.93,
                    "bbox": [10, 20, 120, 160],
                    "risk": "danger",
                    "source": "backend_hazard_yolo",
                    "metadata": {
                        "detections": [
                            {"label": "fire", "confidence": 0.93, "bbox": [10, 20, 120, 160]},
                        ],
                    },
                }

        self.vision.hazard_detector = FakeHazardDetector()  # type: ignore[assignment]

        event = await self.vision._detect_and_record_backend_hazard("care", changed_only=True)

        self.assertIsNotNone(event)
        self.assertEqual(self.state.vision[0]["label"], "fire")
        self.assertEqual(self.state.alarms[0]["type"], "vision_fire")
        self.assertEqual(self.state.alarms[0]["level"], "danger")
        self.assertEqual(self.state.alarms[0]["metadata"]["vision_mode"], "care")

    async def test_hazard_mode_uses_backend_hazard_detector_only(self) -> None:
        class FakeHazardDetector:
            def status(self) -> dict[str, object]:
                return {"enabled": True, "available": True}

            def detect(self, stream_url: str) -> dict[str, object]:
                return {
                    "label": "smoke",
                    "label_zh": "烟雾",
                    "confidence": 0.91,
                    "bbox": [10, 20, 120, 160],
                    "risk": "danger",
                    "source": "backend_hazard_yolo",
                    "metadata": {
                        "detections": [
                            {"label": "smoke", "confidence": 0.91, "bbox": [10, 20, 120, 160]},
                        ],
                    },
                }

        def fake_post_json(path: str, payload: dict[str, object]) -> dict[str, object]:
            raise AssertionError("hazard mode should not call remote car YOLO detection")

        self.config.vision.mode = "remote"
        self.vision.hazard_detector = FakeHazardDetector()  # type: ignore[assignment]
        self.vision._post_json = fake_post_json  # type: ignore[method-assign]

        event = await self.vision.detect_once(None, "hazard")

        self.assertEqual(event["label"], "smoke")
        self.assertEqual(event["target_filter"], ["smoke", "fire"])
        self.assertEqual(self.state.alarms[0]["type"], "vision_smoke")
        self.assertEqual(self.state.alarms[0]["metadata"]["vision_mode"], "hazard")

    async def test_hazard_alarm_is_not_duplicated_until_clear(self) -> None:
        class FakeHazardDetector:
            def status(self) -> dict[str, object]:
                return {"enabled": True, "available": True}

            def detect(self, stream_url: str) -> dict[str, object]:
                return {
                    "label": "fire",
                    "label_zh": "火灾",
                    "confidence": 0.91,
                    "bbox": [10, 20, 120, 160],
                    "risk": "danger",
                    "source": "backend_hazard_yolo",
                    "metadata": {
                        "detections": [
                            {"label": "fire", "confidence": 0.91, "bbox": [10, 20, 120, 160]},
                        ],
                    },
                }

        self.vision.hazard_detector = FakeHazardDetector()  # type: ignore[assignment]

        await self.vision.detect_once(None, "hazard")
        first_alarm = self.state.alarms[0]
        await self.vision.detect_once(None, "hazard")
        await self.vision.handle_alarm_confirm(first_alarm)
        await self.vision.detect_once(None, "hazard")

        fire_alarms = [alarm for alarm in self.state.alarms if alarm["type"] == "vision_fire"]
        self.assertEqual(len(fire_alarms), 1)

        class ClearHazardDetector:
            def status(self) -> dict[str, object]:
                return {"enabled": True, "available": True}

            def detect(self, stream_url: str) -> None:
                return None

        self.vision.hazard_detector = ClearHazardDetector()  # type: ignore[assignment]
        await self.vision.detect_once(None, "hazard")

        self.vision.hazard_detector = FakeHazardDetector()  # type: ignore[assignment]
        await self.vision.detect_once(None, "hazard")

        fire_alarms = [alarm for alarm in self.state.alarms if alarm["type"] == "vision_fire"]
        self.assertEqual(len(fire_alarms), 2)

    async def test_confirming_hazard_alarm_stops_repeating_buzzer(self) -> None:
        class FakeHazardDetector:
            def status(self) -> dict[str, object]:
                return {"enabled": True, "available": True}

            def detect(self, stream_url: str) -> dict[str, object]:
                return {
                    "label": "fire",
                    "label_zh": "火灾",
                    "confidence": 0.91,
                    "bbox": [10, 20, 120, 160],
                    "risk": "danger",
                    "source": "backend_hazard_yolo",
                    "metadata": {
                        "detections": [
                            {"label": "fire", "confidence": 0.91, "bbox": [10, 20, 120, 160]},
                        ],
                    },
                }

        buzzer_calls: list[tuple[str, dict[str, object]]] = []

        async def fake_auxiliary(action: str, values: dict[str, object]) -> None:
            buzzer_calls.append((action, values))

        self.vision.hazard_detector = FakeHazardDetector()  # type: ignore[assignment]
        self.vision.auxiliary_callback = fake_auxiliary

        await self.vision.detect_once(None, "hazard")
        await asyncio.sleep(0)

        self.assertEqual(self.state.alarms[0]["type"], "vision_fire")
        self.assertTrue(buzzer_calls)
        self.assertIsNotNone(self.vision._hazard_buzzer_task)

        await self.vision.handle_alarm_confirm(self.state.alarms[0])

        self.assertEqual(self.vision._active_hazard_alarm_ids, {})
        self.assertTrue(self.vision._hazard_buzzer_task is None or self.vision._hazard_buzzer_task.done())

    async def test_hazard_mode_records_clear_when_no_backend_hazard_detected(self) -> None:
        class FakeHazardDetector:
            def status(self) -> dict[str, object]:
                return {"enabled": True, "available": True}

            def detect(self, stream_url: str) -> None:
                return None

        self.vision.hazard_detector = FakeHazardDetector()  # type: ignore[assignment]

        event = await self.vision.detect_once(None, "hazard")

        self.assertEqual(event["label"], "clear")
        self.assertEqual(event["confidence"], 0.0)
        self.assertEqual(event["target_filter"], ["smoke", "fire"])
        self.assertEqual(self.state.alarms, [])

    async def test_search_mode_reports_selected_target(self) -> None:
        event = await self.vision.detect_once(["person"], "search")

        self.assertEqual(event["label"], "person")
        self.assertEqual(len(self.state.reports), 1)
        self.assertIn("搜索目标发现", self.state.reports[0]["title"])

    async def test_continuous_detection_records_only_changed_events(self) -> None:
        self.config.vision.mode = "remote"
        responses = [
            {"label": "person", "label_zh": "人员", "confidence": 0.92, "bbox": [10, 20, 110, 180]},
            {"label": "person", "label_zh": "人员", "confidence": 0.88, "bbox": [11, 19, 111, 181]},
            {"label": "dog", "label_zh": "宠物", "confidence": 0.86, "bbox": [10, 20, 110, 180]},
        ]

        def fake_get_json(path: str) -> dict[str, object]:
            return {
                "targets": [
                    {"id": "person", "label": "person", "label_zh": "人员"},
                    {"id": "dog", "label": "dog", "label_zh": "宠物"},
                ]
            }

        def fake_post_json(path: str, payload: dict[str, object]) -> dict[str, object]:
            return responses.pop(0)

        self.vision._get_json = fake_get_json  # type: ignore[method-assign]
        self.vision._post_json = fake_post_json  # type: ignore[method-assign]

        first = await self.vision.detect_changed_once(["person", "dog"])
        second = await self.vision.detect_changed_once(["person", "dog"])
        third = await self.vision.detect_changed_once(["person", "dog"])

        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertTrue(third["changed"])
        self.assertEqual(len(self.state.vision), 2)
        self.assertEqual(self.state.vision[0]["label"], "dog")

    async def test_mjpeg_reader_accepts_short_stream_chunks(self) -> None:
        class ChunkedResponse:
            def __init__(self) -> None:
                payload = b"\xff\xd8" + (b"a" * 1200) + b"\xff\xd9"
                self.chunks = [b"--frame\r\n", payload[:1], payload[1:400], payload[400:900], payload[900:], b"\r\n"]

            def read1(self, size: int) -> bytes:
                return self.chunks.pop(0) if self.chunks else b""

        jpeg = _MjpegReader("http://example.test/video")._read_one_jpeg(ChunkedResponse())

        self.assertTrue(jpeg.startswith(b"\xff\xd8"))
        self.assertTrue(jpeg.endswith(b"\xff\xd9"))
        self.assertGreater(len(jpeg), 1024)


if __name__ == "__main__":
    unittest.main()
