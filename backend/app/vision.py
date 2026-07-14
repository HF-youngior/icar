from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Iterable
from typing import Any, Awaitable, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import AppConfig
from .hazard_vision import BackendHazardDetector
from .state import StateHub


class VisionService:
    MODES: dict[str, dict[str, str]] = {
        "normal": {"label": "普通检测模式", "description": "只记录检测事件，不触发告警。"},
        "travel": {"label": "旅游安防模式", "description": "家中无人时使用，检测到人员就告警。"},
        "care": {"label": "看护检测模式", "description": "检测人员姿态，连续疑似摔倒时告警。"},
        "search": {"label": "搜索模式", "description": "检测到选定目标时生成报告。"},
    }

    TARGETS: dict[str, dict[str, str]] = {
        "person": {"label": "person", "label_zh": "人员", "risk": "warning"},
        "fire": {"label": "fire", "label_zh": "火灾", "risk": "danger"},
        "smoke": {"label": "smoke", "label_zh": "烟雾", "risk": "danger"},
        "cat": {"label": "cat", "label_zh": "宠物", "risk": "normal"},
        "dog": {"label": "dog", "label_zh": "宠物", "risk": "normal"},
        "door_open": {"label": "door_open", "label_zh": "门窗未关闭", "risk": "warning"},
        "clear": {"label": "clear", "label_zh": "未发现异常", "risk": "normal"},
    }

    HAZARD_LABELS: dict[str, str] = {
        "fire": "火灾",
        "smoke": "烟雾",
    }
    FALL_HEIGHT_DROP_RATIO = 0.6
    FALL_CONFIRM_FRAMES = 3

    def __init__(self, config: AppConfig, state: StateHub) -> None:
        self.config = config
        self.state = state
        self._task: asyncio.Task[None] | None = None
        self.auxiliary_callback: Callable[[str, dict[str, Any]], Awaitable[Any]] | None = None
        self.hazard_detector = BackendHazardDetector(config)
        self._target_order = list(self.TARGETS)
        self._target_index = 0
        self._last_detection_signature: tuple[Any, ...] | None = None
        self._last_hazard_signature: tuple[Any, ...] | None = None
        self._travel_person_alarm_active = False
        self._fall_candidate_frames = 0
        self._fall_baseline_height: float | None = None
        self._fall_alarm_active = False

    def available_targets(self) -> list[dict[str, str]]:
        remote_targets = self._remote_targets()
        if remote_targets:
            return remote_targets
        if self.config.vision.mode == "remote":
            return []
        return [
            {"id": target_id, "label": data["label"], "label_zh": data["label_zh"]}
            for target_id, data in self.TARGETS.items()
            if target_id != "clear"
        ]

    def status(self) -> dict[str, Any]:
        stream_url = self._stream_url()
        return {
            "running": self._task is not None and not self._task.done(),
            "targets": list(self.state.vision_control.get("targets", ["person"])),
            "mode": self.state.vision_control.get("mode") or "normal",
            "source": self.state.vision_control.get("source") or self._mode_source(),
            "stream_url": self.state.vision_control.get("stream_url") or stream_url,
            "backend_mode": self.config.vision.mode,
            "service_url": self._service_base_url() if self._remote_enabled() else "",
            "annotated_stream_url": self.annotated_stream_proxy_url(),
            "modes": self.available_modes(),
            "backend_hazard": self.hazard_detector.status(),
        }

    def available_modes(self) -> list[dict[str, Any]]:
        return [
            {"id": mode_id, **data, "enabled": True}
            for mode_id, data in self.MODES.items()
        ]

    def annotated_stream_proxy_url(self, targets: Iterable[str] | None = None, mode: str | None = None) -> str:
        mode_id = self._normalize_mode(mode or self.state.vision_control.get("mode"))
        query = urlencode({"targets": ",".join(self._normalize_targets(targets, mode_id))})
        return f"/api/vision/annotated-stream?{query}"

    def remote_annotated_stream_url(self, targets: Iterable[str] | None = None, mode: str | None = None) -> str:
        mode_id = self._normalize_mode(mode or self.state.vision_control.get("mode"))
        query = urlencode({
            "stream_url": self._stream_url(),
            "targets": ",".join(self._normalize_targets(targets, mode_id)),
        })
        return f"{self._service_base_url()}/stream?{query}"

    async def start_detection(self, targets: Iterable[str] | None = None, mode: str | None = None) -> dict[str, Any]:
        mode_id = self._normalize_mode(mode)
        normalized = self._normalize_targets(targets, mode_id)
        self._last_detection_signature = None
        self._last_hazard_signature = None
        self._travel_person_alarm_active = False
        self._reset_fall_state()
        await self.state.update_vision_control(
            running=True,
            targets=normalized,
            mode=mode_id,
            source=self._mode_source(),
            stream_url=self._stream_url(),
        )
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
        return self.status()

    async def stop_detection(self) -> dict[str, Any]:
        task = self._task
        self._task = None
        self._last_detection_signature = None
        self._last_hazard_signature = None
        self._travel_person_alarm_active = False
        self._reset_fall_state()
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self.state.update_vision_control(running=False)
        return self.status()

    async def _loop(self) -> None:
        try:
            while True:
                await self.detect_changed_once()
                await asyncio.sleep(self.config.vision_tick_sec)
        except asyncio.CancelledError:
            raise

    async def detect_once(self, targets: Iterable[str] | None = None, mode: str | None = None) -> dict[str, Any]:
        event = await self._build_detection_event(targets, mode)
        await self._record_detection_event(event)
        await self._update_fall_detection(event)
        await self._detect_and_record_backend_hazard(event["mode"], changed_only=False)
        self._last_detection_signature = self._event_signature(event)
        return event

    async def detect_changed_once(self, targets: Iterable[str] | None = None, mode: str | None = None) -> dict[str, Any]:
        event = await self._build_detection_event(targets, mode)
        signature = self._event_signature(event)
        changed = signature != self._last_detection_signature
        event["changed"] = changed
        await self._update_fall_detection(event)
        recorded = await self._update_travel_person_alarm(event)
        await self._detect_and_record_backend_hazard(event["mode"], changed_only=True)
        if changed and not recorded:
            await self._record_detection_event(event)
        if changed:
            self._last_detection_signature = signature
        return event

    async def _build_detection_event(self, targets: Iterable[str] | None = None, mode: str | None = None) -> dict[str, Any]:
        mode_id = self._normalize_mode(mode or self.state.vision_control.get("mode"))
        raw_targets = self.state.vision_control.get("targets") if targets is None else targets
        selected = self._normalize_targets(raw_targets, mode_id)
        remote_event = await self._detect_remote(selected)
        if remote_event is not None:
            remote_event["mode"] = mode_id
            return remote_event

        base = self._next_target(selected)
        return {
            **base,
            "confidence": round(random.uniform(0.72, 0.96), 2),
            "bbox": [
                random.randint(80, 220),
                random.randint(40, 140),
                random.randint(260, 420),
                random.randint(220, 380),
            ],
            "image_url": "/assets/sample-detection.svg",
            "source": "camera_stream",
            "stream_url": self._stream_url(),
            "target_filter": selected,
            "mode": mode_id,
        }

    async def _record_detection_event(self, event: dict[str, Any]) -> None:
        await self.state.add_vision_event(event)
        mode_id = self._normalize_mode(event.get("mode"))
        mode_label = self.MODES[mode_id]["label"]
        labels = self._detected_labels(event)
        await self._record_hazard_alarm(event, mode_id, mode_label, labels)
        if mode_id == "travel" and "person" in labels and not self._travel_person_alarm_active:
            self._travel_person_alarm_active = True
            metadata = {
                **event,
                "vision_mode": mode_id,
                "vision_mode_label": mode_label,
            }
            await self.state.add_alarm(
                alarm_type="vision_person_travel",
                level="warning",
                message=f"{mode_label}检测到人员，请确认家庭环境。",
                source="vision",
                metadata=metadata,
            )
        elif mode_id == "travel" and "person" not in labels:
            self._travel_person_alarm_active = False
        elif mode_id == "search":
            found = self._search_matches(event)
            if found:
                await self.state.add_report(
                    title=f"搜索目标发现：{', '.join(found)}",
                    summary=f"视觉搜索模式检测到目标：{', '.join(found)}。",
                    details={"vision_event": event, "targets": event.get("target_filter") or []},
                )

    def _normalize_mode(self, mode: Any) -> str:
        mode_id = str(mode or "normal").strip().lower()
        if mode_id in self.MODES:
            return mode_id
        return "normal"

    def _detected_labels(self, event: dict[str, Any]) -> list[str]:
        labels: list[str] = []
        for detection in self._event_detections(event):
            label = str(detection[0]).strip().lower()
            if label and label != "clear" and label not in labels:
                labels.append(label)
        if labels:
            return labels
        label = str(event.get("label") or "").strip().lower()
        return [label] if label and label != "clear" else []

    def _search_matches(self, event: dict[str, Any]) -> list[str]:
        selected = {str(item).strip().lower() for item in event.get("target_filter") or [] if str(item).strip()}
        if not selected:
            return []
        return [label for label in self._detected_labels(event) if label in selected]

    async def _detect_and_record_backend_hazard(self, mode: str, changed_only: bool) -> dict[str, Any] | None:
        mode_id = self._normalize_mode(mode)
        if mode_id not in {"travel", "care"}:
            return None
        try:
            hazard_event = await asyncio.to_thread(self.hazard_detector.detect, self._stream_url())
        except Exception:
            return None
        if hazard_event is None:
            self._last_hazard_signature = None
            return None
        hazard_event["mode"] = mode_id
        hazard_event["stream_url"] = self._stream_url()
        hazard_event["target_filter"] = list(self.config.vision.hazard_labels)
        signature = self._hazard_signature(hazard_event)
        if changed_only and signature == self._last_hazard_signature:
            return hazard_event
        await self._record_detection_event(hazard_event)
        self._last_hazard_signature = signature
        return hazard_event

    def _hazard_signature(self, event: dict[str, Any]) -> tuple[Any, ...]:
        labels = sorted(label for label in self._detected_labels(event) if label in self.HAZARD_LABELS)
        return tuple(labels) if labels else ("clear",)

    async def _update_travel_person_alarm(self, event: dict[str, Any]) -> bool:
        mode_id = self._normalize_mode(event.get("mode"))
        if mode_id != "travel":
            self._travel_person_alarm_active = False
            return False
        labels = self._detected_labels(event)
        if "person" not in labels:
            self._travel_person_alarm_active = False
            return False
        if self._travel_person_alarm_active:
            return False
        await self._record_detection_event(event)
        return True

    async def _record_hazard_alarm(
        self,
        event: dict[str, Any],
        mode_id: str,
        mode_label: str,
        labels: list[str],
    ) -> None:
        if mode_id not in {"travel", "care"}:
            return
        found = [label for label in labels if label in self.HAZARD_LABELS]
        if not found:
            return
        label = found[0]
        label_zh = self.HAZARD_LABELS[label]
        await self.state.add_alarm(
            alarm_type=f"vision_{label}",
            level="danger",
            message=f"{mode_label}检测到{label_zh}，请立即确认环境。",
            source="vision",
            metadata={
                **event,
                "vision_mode": mode_id,
                "vision_mode_label": mode_label,
                "hazard": label,
            },
        )

    async def _update_fall_detection(self, event: dict[str, Any]) -> None:
        mode_id = self._normalize_mode(event.get("mode"))
        if mode_id != "care":
            self._reset_fall_state()
            return
        person_height = self._person_height(event)
        if person_height is None:
            self._reset_fall_state()
            return
        if self._fall_baseline_height is None:
            self._fall_baseline_height = person_height
            self._fall_candidate_frames = 0
            self._fall_alarm_active = False
            return
        drop_threshold = self._fall_baseline_height * self.FALL_HEIGHT_DROP_RATIO
        if person_height > drop_threshold:
            self._fall_baseline_height = max(self._fall_baseline_height, person_height)
            self._fall_candidate_frames = 0
            self._fall_alarm_active = False
            return
        self._fall_candidate_frames += 1
        if self._fall_candidate_frames < self.FALL_CONFIRM_FRAMES or self._fall_alarm_active:
            return
        self._fall_alarm_active = True
        mode_label = self.MODES[mode_id]["label"]
        await self.state.add_alarm(
            alarm_type="vision_fall",
            level="danger",
            message=f"{mode_label}连续检测到疑似摔倒，请立即确认。",
            source="vision",
            metadata={
                **event,
                "vision_mode": mode_id,
                "vision_mode_label": mode_label,
                "fall_rule": {
                    "requires_height_drop": True,
                    "height_drop_ratio": self.FALL_HEIGHT_DROP_RATIO,
                    "baseline_height": self._fall_baseline_height,
                    "current_height": person_height,
                    "confirm_frames": self.FALL_CONFIRM_FRAMES,
                    "current_frames": self._fall_candidate_frames,
                },
            },
        )
        await self._trigger_fall_buzzer()

    async def _trigger_fall_buzzer(self) -> None:
        if self.auxiliary_callback is None:
            return
        for index in range(2):
            try:
                await self.auxiliary_callback("buzzer", {"duration_ms": 160})
            except Exception:
                return
            if index == 0:
                await asyncio.sleep(0.18)

    def _reset_fall_state(self) -> None:
        self._fall_candidate_frames = 0
        self._fall_baseline_height = None
        self._fall_alarm_active = False

    def _person_height(self, event: dict[str, Any]) -> float | None:
        heights: list[float] = []
        for bbox in self._person_bboxes(event):
            x1, y1, x2, y2 = [float(value or 0) for value in bbox[:4]]
            height = max(0.0, y2 - y1)
            if height > 0:
                heights.append(height)
        return max(heights) if heights else None

    def _person_bboxes(self, event: dict[str, Any]) -> list[list[Any]]:
        boxes: list[list[Any]] = []
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        raw_detections = metadata.get("detections") if isinstance(metadata, dict) else None
        if isinstance(raw_detections, list):
            for item in raw_detections:
                label = ""
                bbox: Any = None
                if isinstance(item, dict):
                    label = str(item.get("label") or item.get("class_name") or item.get("name") or "").strip().lower()
                    bbox = item.get("bbox") or item.get("box")
                elif isinstance(item, (list, tuple)) and len(item) >= 6:
                    label = str(item[3] or "").strip().lower()
                    bbox = item[5]
                if label == "person" and isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                    boxes.append(list(bbox[:4]))
        label = str(event.get("label") or "").strip().lower()
        bbox = event.get("bbox")
        if label == "person" and isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            boxes.append(list(bbox[:4]))
        return boxes

    def _event_signature(self, event: dict[str, Any]) -> tuple[Any, ...]:
        detections = self._event_detections(event)
        if not detections:
            return ("clear",)
        return tuple(sorted(detections))

    def _event_detections(self, event: dict[str, Any]) -> list[tuple[Any, ...]]:
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        raw_detections = metadata.get("detections") if isinstance(metadata, dict) else None
        detections: list[tuple[Any, ...]] = []
        if isinstance(raw_detections, list):
            for item in raw_detections:
                parsed = self._parse_detection_item(item, event)
                if parsed is not None:
                    detections.append(parsed)
        if detections:
            return detections
        label = str(event.get("label") or "clear").strip().lower() or "clear"
        if label == "clear":
            return []
        return [(label, *self._bbox_bucket(event.get("bbox"), event))]

    def _parse_detection_item(self, item: Any, event: dict[str, Any]) -> tuple[Any, ...] | None:
        if isinstance(item, dict):
            label = str(item.get("label") or item.get("class_name") or item.get("name") or event.get("label") or "").strip().lower()
            bbox = item.get("bbox") or item.get("box")
        elif isinstance(item, (list, tuple)) and len(item) >= 6:
            label = str(item[3] or event.get("label") or "").strip().lower()
            bbox = item[5]
        else:
            return None
        if not label or label == "clear":
            return None
        return (label, *self._bbox_bucket(bbox, event))

    def _bbox_bucket(self, bbox: Any, event: dict[str, Any]) -> tuple[int, int, int, int]:
        if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
            return (0, 0, 0, 0)
        frame_width = max(1.0, float(event.get("frame_width") or 640))
        frame_height = max(1.0, float(event.get("frame_height") or 480))
        step_x = max(24.0, frame_width * 0.04)
        step_y = max(24.0, frame_height * 0.04)
        values = [float(value or 0) for value in bbox[:4]]
        return (
            round(values[0] / step_x),
            round(values[1] / step_y),
            round(values[2] / step_x),
            round(values[3] / step_y),
        )

    def _normalize_targets(self, targets: Iterable[str] | None, mode: str | None = None) -> list[str]:
        mode_id = self._normalize_mode(mode or self.state.vision_control.get("mode"))
        if mode_id == "normal":
            return []
        if mode_id in {"travel", "care"}:
            return ["person", "smoke", "fire"]
        remote_targets = self._remote_targets() if self.config.vision.mode == "remote" else []
        if self.config.vision.mode == "remote":
            allowed_remote = {item["id"] for item in remote_targets}
            if not allowed_remote:
                return []
            normalized_remote: list[str] = []
            for target in targets or []:
                key = str(target).strip().lower()
                if key in allowed_remote and key not in normalized_remote:
                    normalized_remote.append(key)
            return normalized_remote or [remote_targets[0]["id"]]
        if targets is None:
            return ["person"]
        normalized: list[str] = []
        allowed_remote = {item["id"] for item in self.available_targets()} if self._remote_enabled() else set()
        for target in targets:
            key = str(target).strip().lower()
            if key == "clear" or key in normalized:
                continue
            if key in self.TARGETS or key in allowed_remote:
                normalized.append(key)
        return normalized or ["person"]

    def _next_target(self, allowed: list[str]) -> dict[str, Any]:
        for _ in range(len(self._target_order)):
            target_id = self._target_order[self._target_index % len(self._target_order)]
            self._target_index += 1
            if target_id != "clear" and (not allowed or target_id in allowed):
                return self.TARGETS[target_id]
        return self.TARGETS["person"]

    def _remote_enabled(self) -> bool:
        return self.config.vision.mode in {"auto", "remote"}

    def _mode_source(self) -> str:
        return "remote_yolo_stream" if self._remote_enabled() else "camera_stream"

    def _stream_url(self) -> str:
        return self.config.vision.stream_url.strip() or f"http://{self.config.car.host}:6500/video_feed"

    def _service_base_url(self) -> str:
        configured = self.config.vision.service_base_url.strip()
        if configured:
            return configured.rstrip("/")
        host = self.config.vision.service_host.strip() or self.config.car.host
        return f"http://{host}:{self.config.vision.service_port}"

    async def _detect_remote(self, targets: list[str]) -> dict[str, Any] | None:
        if not self._remote_enabled():
            return None
        try:
            payload = {
                "targets": targets,
                "stream_url": self._stream_url(),
            }
            response = await asyncio.to_thread(self._post_json, self.config.vision.detect_path, payload)
            return self._normalize_remote_event(response, targets)
        except Exception:
            if self.config.vision.mode == "remote":
                raise
            return None

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._service_base_url()}{path}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=self.config.vision.request_timeout_sec) as response:
            return json.loads(response.read().decode("utf-8"))

    def _get_json(self, path: str) -> dict[str, Any]:
        request = Request(f"{self._service_base_url()}{path}", headers={"Accept": "application/json"}, method="GET")
        with urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def _remote_targets(self) -> list[dict[str, str]]:
        if not self._remote_enabled():
            return []
        try:
            data = self._get_json(self.config.vision.health_path)
        except Exception:
            return []
        targets = data.get("targets")
        if not isinstance(targets, list):
            return []
        normalized: list[dict[str, str]] = []
        for item in targets:
            if not isinstance(item, dict):
                continue
            target_id = str(item.get("id") or item.get("label") or "").strip().lower()
            if not target_id:
                continue
            label = str(item.get("label") or target_id).strip()
            label_zh = str(item.get("label_zh") or label).strip()
            normalized.append({"id": target_id, "label": label, "label_zh": label_zh})
        return normalized

    def _normalize_remote_event(self, response: dict[str, Any], targets: list[str]) -> dict[str, Any]:
        label = str(response.get("label") or "person").strip().lower() or "person"
        base = self.TARGETS.get(label, {"label": label, "label_zh": response.get("label_zh") or label, "risk": "normal"})
        bbox = response.get("bbox") or [120, 80, 260, 360]
        confidence = float(response.get("confidence") or 0.8)
        return {
            "label": label,
            "label_zh": response.get("label_zh") or base["label_zh"],
            "confidence": max(0.0, min(1.0, confidence)),
            "risk": response.get("risk") or base["risk"],
            "bbox": bbox,
            "frame_width": response.get("frame_width"),
            "frame_height": response.get("frame_height"),
            "image_url": response.get("image_url") or "/assets/sample-detection.svg",
            "source": response.get("source") or "remote_yolo_stream",
            "stream_url": response.get("stream_url") or self._stream_url(),
            "target_filter": targets,
            "metadata": response.get("metadata") or {},
        }
