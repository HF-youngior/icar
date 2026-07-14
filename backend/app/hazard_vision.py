from __future__ import annotations

import base64
import os
import pathlib
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .config import AppConfig, resolve_project_path


class BackendHazardDetector:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._runner: _Yolov5Runner | None = None
        self._load_error = ""
        self._lock = threading.Lock()

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.config.vision.hazard_enabled,
            "available": self.available,
            "error": self._load_error,
            "weights": self.config.vision.hazard_weights,
            "labels": list(self.config.vision.hazard_labels),
        }

    @property
    def available(self) -> bool:
        return self._ensure_runner() is not None

    def detect(self, stream_url: str) -> dict[str, Any] | None:
        runner = self._ensure_runner()
        if runner is None:
            return None
        frame = _MjpegReader(stream_url).read_frame()
        return runner.detect(frame)

    def _ensure_runner(self) -> "_Yolov5Runner | None":
        if not self.config.vision.hazard_enabled:
            return None
        if self._runner is not None:
            return self._runner
        with self._lock:
            if self._runner is not None:
                return self._runner
            try:
                self._runner = _Yolov5Runner(
                    yolo_root=_resolve_optional_path(self.config.vision.hazard_yolo_root),
                    weights=_resolve_required_path(self.config.vision.hazard_weights),
                    data=_resolve_optional_path(self.config.vision.hazard_data),
                    conf=float(self.config.vision.hazard_conf),
                    labels=[label.lower() for label in self.config.vision.hazard_labels],
                )
                self._load_error = ""
            except Exception as exc:
                self._load_error = str(exc)
                self._runner = None
            return self._runner


class _Yolov5Runner:
    def __init__(self, yolo_root: Path | None, weights: Path, data: Path | None, conf: float, labels: list[str]) -> None:
        if yolo_root is None:
            raise ValueError("ICAR_HAZARD_YOLO_ROOT is required for backend smoke/fire detection")
        if str(yolo_root) not in sys.path:
            sys.path.insert(0, str(yolo_root))

        import cv2  # type: ignore
        import numpy as np  # type: ignore
        import torch  # type: ignore

        _allow_trusted_yolov5_checkpoints(torch)
        from models.common import DetectMultiBackend  # type: ignore
        from utils.augmentations import letterbox  # type: ignore
        from utils.general import check_img_size, non_max_suppression, scale_boxes  # type: ignore
        from utils.torch_utils import select_device  # type: ignore

        self.cv2 = cv2
        self.np = np
        self.torch = torch
        self.letterbox = letterbox
        self.non_max_suppression = non_max_suppression
        self.scale_boxes = scale_boxes
        self.device = select_device("")
        data_arg = str(data) if data is not None else None
        self.model = DetectMultiBackend(str(weights), device=self.device, data=data_arg)
        self.stride = self.model.stride
        self.names = self.model.names
        self.imgsz = check_img_size((640, 640), s=self.stride)
        self.conf = conf
        self.labels = labels
        self.class_name_to_id = _class_name_to_id(self.names)
        self.classes = [self.class_name_to_id[label] for label in labels if label in self.class_name_to_id]
        self.lock = threading.Lock()

    def detect(self, frame: Any, targets: list[str] | None = None, source: str = "backend_hazard_yolo") -> dict[str, Any] | None:
        frame_height, frame_width = frame.shape[:2]
        detections: list[dict[str, Any]] = []
        classes = self._target_classes(targets) if targets else self.classes
        if targets and not classes:
            return None
        with self.lock:
            result_img, detections = self._detect_frame(frame, classes)
        if not detections:
            return None
        best = max(detections, key=lambda item: float(item.get("confidence") or 0))
        return {
            "label": best["label"],
            "label_zh": _hazard_label_zh(best["label"]),
            "confidence": best["confidence"],
            "bbox": best["bbox"],
            "risk": "danger",
            "frame_width": frame_width,
            "frame_height": frame_height,
            "image_url": self._encode_image_url(result_img),
            "source": source,
            "target_filter": targets or self.labels,
            "metadata": {
                "detections": detections,
                "frame_width": frame_width,
                "frame_height": frame_height,
                "backend_model": True,
            },
        }

    def _target_classes(self, targets: list[str] | None) -> list[int]:
        return [self.class_name_to_id[target] for target in targets or [] if target in self.class_name_to_id]

    def _detect_frame(self, frame: Any, classes: list[int] | None = None) -> tuple[Any, list[dict[str, Any]]]:
        im = self.letterbox(frame, self.imgsz, stride=self.stride, auto=True)[0]
        im = im.transpose((2, 0, 1))[::-1]
        im = self.np.ascontiguousarray(im)
        tensor = self.torch.from_numpy(im).to(self.device).float()
        tensor /= 255
        if len(tensor.shape) == 3:
            tensor = tensor[None]

        pred = self.model(tensor)
        pred = self.non_max_suppression(pred, self.conf, 0.45, classes or None, False, max_det=50)
        result = frame.copy()
        detections: list[dict[str, Any]] = []
        for det in pred:
            if len(det):
                det[:, :4] = self.scale_boxes(tensor.shape[2:], det[:, :4], frame.shape).round()
                for *xyxy, conf, cls in reversed(det):
                    x1, y1, x2, y2 = [int(value.item()) for value in xyxy]
                    class_id = int(cls.item())
                    label = _class_name(self.names, class_id).lower()
                    confidence = float(conf.item())
                    bbox = [x1, y1, x2, y2]
                    color = (0, 80, 255)
                    text = f"{label} {confidence * 100:.0f}%"
                    self.cv2.rectangle(result, (x1, y1), (x2, y2), color, 2)
                    text_size, baseline = self.cv2.getTextSize(text, self.cv2.FONT_HERSHEY_SIMPLEX, 0.62, 2)
                    text_width, text_height = text_size
                    text_x = max(0, x1)
                    text_y = y1 - 8 if y1 - text_height - 12 >= 0 else y1 + text_height + 10
                    box_y1 = max(0, text_y - text_height - baseline - 4)
                    box_y2 = min(result.shape[0] - 1, text_y + baseline + 4)
                    box_x2 = min(result.shape[1] - 1, text_x + text_width + 8)
                    self.cv2.rectangle(result, (text_x, box_y1), (box_x2, box_y2), color, -1)
                    self.cv2.putText(
                        result,
                        text,
                        (text_x + 4, text_y),
                        self.cv2.FONT_HERSHEY_SIMPLEX,
                        0.62,
                        (255, 255, 255),
                        2,
                    )
                    detections.append({
                        "label": label,
                        "class_name": label,
                        "confidence": confidence,
                        "bbox": bbox,
                    })
        return result, detections

    def _encode_image_url(self, image: Any) -> str:
        ok, encoded = self.cv2.imencode(".jpg", image, [int(self.cv2.IMWRITE_JPEG_QUALITY), 82])
        if not ok:
            return ""
        payload = base64.b64encode(encoded.tobytes()).decode("ascii")
        return f"data:image/jpeg;base64,{payload}"


class _MjpegReader:
    def __init__(self, stream_url: str) -> None:
        self.stream_url = stream_url

    def read_frame(self) -> Any:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        request = Request(self.stream_url, headers={"User-Agent": "iCar-Backend-Hazard/1.0"})
        with urlopen(request, timeout=8) as response:
            data = self._read_one_jpeg(response)
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Failed to decode JPEG frame")
        return image

    def _read_one_jpeg(self, response: Any) -> bytes:
        buffer = bytearray()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            chunk = response.read(4096)
            if not chunk:
                break
            buffer.extend(chunk)
            start = buffer.find(b"\xff\xd8")
            if start < 0:
                del buffer[:-2]
                continue
            end = buffer.find(b"\xff\xd9", start + 2)
            if end >= 0:
                return bytes(buffer[start:end + 2])
            if start > 0:
                del buffer[:start]
        raise TimeoutError("Timed out waiting for one JPEG frame from MJPEG stream")


def _resolve_optional_path(path_value: str) -> Path | None:
    if not path_value.strip():
        return None
    path = resolve_project_path(path_value)
    return path


def _resolve_required_path(path_value: str) -> Path:
    path = _resolve_optional_path(path_value)
    if path is None:
        raise ValueError("ICAR_HAZARD_WEIGHTS is required for backend smoke/fire detection")
    if not path.exists():
        raise FileNotFoundError(str(path))
    return path


def _hazard_label_zh(label: str) -> str:
    return {
        "smoke": "烟雾",
        "fire": "火灾",
    }.get(label, label)


def _class_name_to_id(names: Any) -> dict[str, int]:
    if isinstance(names, dict):
        return {str(name).lower(): int(idx) for idx, name in names.items()}
    if isinstance(names, list):
        return {str(name).lower(): idx for idx, name in enumerate(names)}
    return {}


def _class_name(names: Any, class_id: int) -> str:
    if isinstance(names, dict):
        return str(names.get(class_id, class_id))
    if isinstance(names, list) and 0 <= class_id < len(names):
        return str(names[class_id])
    return str(class_id)


def _allow_trusted_yolov5_checkpoints(torch_module: Any) -> None:
    if os.name != "nt":
        pathlib.WindowsPath = pathlib.PosixPath
    if getattr(torch_module.load, "_icar_yolov5_compat", False):
        return
    original_load = torch_module.load

    def load_with_trusted_yolov5_defaults(*args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("weights_only", False)
        return original_load(*args, **kwargs)

    load_with_trusted_yolov5_defaults._icar_yolov5_compat = True  # type: ignore[attr-defined]
    torch_module.load = load_with_trusted_yolov5_defaults
