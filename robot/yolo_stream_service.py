#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import cv2  # type: ignore
import numpy as np


def default_yolo_root() -> Path:
    candidates = [
        Path("/home/jetson/yolov5-7.0"),
        Path("/home/jetson/yolov5"),
        Path("/home/jetson/Rosmaster-App/yolov5"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path("/home/jetson/yolov5-7.0")


class YoloRunner:
    def __init__(self, yolo_root: Path, weights: str, data: str, classes: list[int] | None) -> None:
        self.yolo_root = yolo_root
        if str(yolo_root) not in sys.path:
            sys.path.insert(0, str(yolo_root))
        from self_detect import YoloDetecter  # type: ignore
        from utils.augmentations import letterbox  # type: ignore
        from utils.general import non_max_suppression, scale_boxes  # type: ignore
        import torch  # type: ignore

        self.detector = YoloDetecter(weights=weights, data=data, classes=classes)
        self.class_name_to_id = {str(name).lower(): idx for idx, name in self.detector.names.items()}
        self.letterbox = letterbox
        self.non_max_suppression = non_max_suppression
        self.scale_boxes = scale_boxes
        self.torch = torch
        self.lock = threading.Lock()

    def available_targets(self) -> list[dict[str, str]]:
        return [
            {"id": str(name).lower(), "label": str(name), "label_zh": str(name)}
            for _, name in sorted(self.detector.names.items())
        ]

    def detect(self, frame: np.ndarray, targets: list[str]) -> dict[str, Any]:
        frame_height, frame_width = frame.shape[:2]
        classes = [self.class_name_to_id[name] for name in targets if name in self.class_name_to_id]
        with self.lock:
            self.detector.classes = classes or None
            res_img, pixel_list = self._detect_frame(frame, classes or None)
        image_url = self._encode_image_url(res_img)
        if not pixel_list:
            return {
                "label": "clear",
                "label_zh": "未发现异常",
                "confidence": 0.98,
                "bbox": [0, 0, 0, 0],
                "risk": "normal",
                "frame_width": frame_width,
                "frame_height": frame_height,
                "image_url": image_url,
                "metadata": {"detections": [], "frame_width": frame_width, "frame_height": frame_height},
            }
        x, y, class_id, class_name, confidence, bbox = pixel_list[0]
        return {
            "label": str(class_name).lower(),
            "label_zh": str(class_name),
            "confidence": confidence,
            "bbox": bbox,
            "risk": "warning" if str(class_name).lower() in {"person", "fire", "smoke", "fall_down"} else "normal",
            "frame_width": frame_width,
            "frame_height": frame_height,
            "image_url": image_url,
            "metadata": {"detections": pixel_list, "frame_width": frame_width, "frame_height": frame_height},
        }

    def _encode_image_url(self, image: np.ndarray) -> str:
        ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        if not ok:
            return ""
        payload = base64.b64encode(encoded.tobytes()).decode("ascii")
        return f"data:image/jpeg;base64,{payload}"

    def _detect_frame(self, frame: np.ndarray, classes: list[int] | None) -> tuple[np.ndarray, list[list[Any]]]:
        im = self.letterbox(frame, self.detector.imgsz, stride=self.detector.model.stride, auto=self.detector.model.pt)[0]
        im = im.transpose((2, 0, 1))[::-1]
        im = np.ascontiguousarray(im)
        tensor = self.torch.from_numpy(im).to(self.detector.device)
        tensor = tensor.half() if self.detector.model.fp16 else tensor.float()
        tensor /= 255
        if len(tensor.shape) == 3:
            tensor = tensor[None]

        pred = self.detector.model(tensor)
        pred = self.non_max_suppression(
            pred,
            self.detector.conf_thres,
            self.detector.iou_thres,
            classes,
            self.detector.agnostic_nms,
            max_det=self.detector.max_det,
        )

        result = frame.copy()
        rows_b, cols_b = frame.shape[:2]
        detections: list[list[Any]] = []
        for det in pred:
            if len(det):
                det[:, :4] = self.scale_boxes(tensor.shape[2:], det[:, :4], frame.shape).round()
                for *xyxy, conf, cls in reversed(det):
                    x1, y1, x2, y2 = [int(value.item()) for value in xyxy]
                    class_id = int(cls.item())
                    confidence = float(conf.item())
                    class_name = str(self.detector.names[class_id])
                    cv2.rectangle(result, (x1, y1), (x2, y2), (38, 244, 255), 2)
                    cv2.putText(
                        result,
                        f"{class_name} {confidence:.2f}",
                        (x1, max(18, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (38, 244, 255),
                        2,
                    )
                    detections.append([
                        (x1 + x2) / 2,
                        (y1 + y2) / 2,
                        class_id,
                        class_name,
                        confidence,
                        [x1, y1, x2, y2],
                    ])
        return result, detections


class MjpegReader:
    def __init__(self, stream_url: str) -> None:
        self.stream_url = stream_url

    def read_frame(self) -> np.ndarray:
        request = Request(self.stream_url, headers={"User-Agent": "iCar-YOLO/1.0"})
        with urlopen(request, timeout=8) as response:
            data = self._read_one_jpeg(response)
        return self._extract_jpeg(data)

    def _read_one_jpeg(self, response) -> bytes:
        buffer = bytearray()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            chunk = response.read(4096)
            if not chunk:
                break
            buffer.extend(chunk)
            start = buffer.find(b"\xff\xd8")
            if start < 0:
                # Keep the buffer bounded while waiting for the JPEG SOI marker.
                del buffer[:-2]
                continue
            end = buffer.find(b"\xff\xd9", start + 2)
            if end >= 0:
                return bytes(buffer[start:end + 2])
            if start > 0:
                del buffer[:start]
        raise TimeoutError("Timed out waiting for one JPEG frame from MJPEG stream")

    def _extract_jpeg(self, data: bytes) -> np.ndarray:
        start = data.find(b"\xff\xd8")
        end = data.find(b"\xff\xd9", start + 2)
        if start < 0 or end < 0:
            raise ValueError("JPEG frame not found in MJPEG payload")
        jpeg = data[start:end + 2]
        image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Failed to decode JPEG frame")
        return image


class ServiceState:
    def __init__(self, runner: YoloRunner, default_stream_url: str) -> None:
        self.runner = runner
        self.default_stream_url = default_stream_url


def build_handler(state: ServiceState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            print(f"{self.client_address[0]} - {fmt % args}", flush=True)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path != "/health":
                self._send_json(404, {"ok": False, "error": "not found"})
                return
            self._send_json(200, {
                "ok": True,
                "service": "yolo_stream",
                "stream_url": state.default_stream_url,
                "targets": state.runner.available_targets(),
            })

        def do_POST(self) -> None:
            if self.path != "/detect":
                self._send_json(404, {"ok": False, "error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length > 0 else b"{}"
                payload = json.loads(raw.decode("utf-8") or "{}")
                stream_url = str(payload.get("stream_url") or state.default_stream_url).strip() or state.default_stream_url
                targets = [str(item).strip().lower() for item in payload.get("targets") or [] if str(item).strip()]
                frame = MjpegReader(stream_url).read_frame()
                result = state.runner.detect(frame, targets)
                result["ok"] = True
                result["source"] = "remote_yolo_stream"
                result["stream_url"] = stream_url
                result["target_filter"] = targets
                self._send_json(200, result)
            except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
                self._send_json(502, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read one frame from the car MJPEG stream and run YOLO detection.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--stream-url", default="http://127.0.0.1:6500/video_feed")
    parser.add_argument("--yolo-root", default=str(default_yolo_root()))
    parser.add_argument("--weights", default="/home/jetson/Yolov5ptFile/yolov5s.pt")
    parser.add_argument("--data", default="/home/jetson/yolov5-7.0/data/coco128.yaml")
    parser.add_argument("--classes", nargs="*", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runner = YoloRunner(Path(args.yolo_root), args.weights, args.data, args.classes)
    server = ThreadingHTTPServer((args.host, args.port), build_handler(ServiceState(runner, args.stream_url)))
    print(f"YOLO stream service listening on {args.host}:{args.port}, stream={args.stream_url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
