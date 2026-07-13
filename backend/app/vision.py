from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Iterable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import AppConfig
from .state import StateHub


class VisionService:
    TARGETS: dict[str, dict[str, str]] = {
        "person": {"label": "person", "label_zh": "人员", "risk": "warning"},
        "cat": {"label": "cat", "label_zh": "宠物", "risk": "normal"},
        "dog": {"label": "dog", "label_zh": "宠物", "risk": "normal"},
        "door_open": {"label": "door_open", "label_zh": "门窗未关闭", "risk": "warning"},
        "clear": {"label": "clear", "label_zh": "未发现异常", "risk": "normal"},
    }

    def __init__(self, config: AppConfig, state: StateHub) -> None:
        self.config = config
        self.state = state
        self._task: asyncio.Task[None] | None = None
        self._target_order = list(self.TARGETS)
        self._target_index = 0

    def available_targets(self) -> list[dict[str, str]]:
        remote_targets = self._remote_targets()
        if remote_targets:
            return remote_targets
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
            "source": self.state.vision_control.get("source") or self._mode_source(),
            "stream_url": self.state.vision_control.get("stream_url") or stream_url,
            "backend_mode": self.config.vision.mode,
            "service_url": self._service_base_url() if self._remote_enabled() else "",
        }

    async def start_detection(self, targets: Iterable[str] | None = None) -> dict[str, Any]:
        normalized = self._normalize_targets(targets)
        await self.state.update_vision_control(
            running=True,
            targets=normalized,
            source=self._mode_source(),
            stream_url=self._stream_url(),
        )
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
        return self.status()

    async def stop_detection(self) -> dict[str, Any]:
        task = self._task
        self._task = None
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
                await self.detect_once()
                await asyncio.sleep(self.config.vision_tick_sec)
        except asyncio.CancelledError:
            raise

    async def detect_once(self, targets: Iterable[str] | None = None) -> dict[str, Any]:
        selected = self._normalize_targets(targets or self.state.vision_control.get("targets"))
        remote_event = await self._detect_remote(selected)
        if remote_event is not None:
            await self.state.add_vision_event(remote_event)
            if remote_event["risk"] == "warning":
                await self.state.add_alarm(
                    alarm_type=f"vision_{remote_event['label']}",
                    level="warning",
                    message=f"视觉检测到{remote_event['label_zh']}，请确认家庭环境。",
                    source="vision",
                    metadata=remote_event,
                )
            return remote_event

        base = self._next_target(selected)
        event = {
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
        }
        await self.state.add_vision_event(event)
        if event["risk"] == "warning":
            await self.state.add_alarm(
                alarm_type=f"vision_{event['label']}",
                level="warning",
                message=f"视觉检测到{event['label_zh']}，请确认家庭环境。",
                source="vision",
                metadata=event,
            )
        return event

    def _normalize_targets(self, targets: Iterable[str] | None) -> list[str]:
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
            if target_id in allowed:
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
