#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import http.server
import socketserver
import threading
import time
from dataclasses import dataclass


try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - depends on Jetson image
    cv2 = None


FALLBACK_JPEG = base64.b64decode(
    b"/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQYGBcUFhYa"
    b"HSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/2wBDAQcHBwoIChMKChMoGhYaKCgoKCgoKCgoKCgoK"
    b"CgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCj/wAARCAAQABADASIAAhEBAxEB/8QA"
    b"HwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIh"
    b"MUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVW"
    b"V1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXG"
    b"x8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQF"
    b"BgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAV"
    b"YnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
    b"hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq"
    b"8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD5/ooooA//2Q=="
)


@dataclass
class CameraConfig:
    host: str
    port: int
    device: str
    width: int
    height: int
    fps: float
    quality: int


class CameraSource:
    def __init__(self, config: CameraConfig) -> None:
        self.config = config
        self.lock = threading.Lock()
        self.capture = None
        self.last_error = "camera not opened"
        self.open()

    def open(self) -> None:
        if cv2 is None:
            self.last_error = "cv2 is not installed"
            print(self.last_error, flush=True)
            return

        candidates: list[int | str]
        if self.config.device == "auto":
            candidates = [0, 1, 2, 3, "/dev/video0", "/dev/video1", "/dev/video2", "/dev/video3"]
        else:
            try:
                candidates = [int(self.config.device)]
            except ValueError:
                candidates = [self.config.device]

        for candidate in candidates:
            cap = cv2.VideoCapture(candidate)
            if not cap or not cap.isOpened():
                try:
                    cap.release()
                except Exception:
                    pass
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
            if not self._can_read_frame(cap):
                try:
                    cap.release()
                except Exception:
                    pass
                print(f"camera candidate has no frames: {candidate}", flush=True)
                continue
            self.capture = cap
            self.last_error = ""
            print(f"camera opened: {candidate}", flush=True)
            return

        self.last_error = "no usable camera device found"
        print(self.last_error, flush=True)

    def _can_read_frame(self, cap) -> bool:
        for _ in range(10):
            ok, frame = cap.read()
            if ok and frame is not None:
                return True
            time.sleep(0.08)
        return False

    def read_jpeg(self) -> bytes:
        with self.lock:
            if self.capture is None:
                return FALLBACK_JPEG
            ok, frame = self.capture.read()
            if not ok or frame is None:
                self.last_error = "camera frame read failed"
                try:
                    self.capture.release()
                except Exception:
                    pass
                self.capture = None
                self.open()
                if self.capture is None:
                    return FALLBACK_JPEG
                ok, frame = self.capture.read()
                if not ok or frame is None:
                    self.last_error = "camera frame read failed after reopen"
                    return FALLBACK_JPEG
            ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.config.quality])
            if not ok:
                self.last_error = "jpeg encode failed"
                return FALLBACK_JPEG
            return encoded.tobytes()

    def status(self) -> str:
        if self.capture is None:
            return f"fallback: {self.last_error}"
        return "ok"

    def close(self) -> None:
        with self.lock:
            if self.capture is not None:
                self.capture.release()
                self.capture = None


class ThreadedHttpServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def build_handler(camera: CameraSource, config: CameraConfig):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            print(f"{self.client_address[0]} - {fmt % args}", flush=True)

        def do_GET(self) -> None:
            if self.path.startswith("/health"):
                body = f"icar camera mjpeg server: {camera.status()}\n".encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path.startswith("/snapshot"):
                frame = camera.read_jpeg()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(frame)))
                self.end_headers()
                self.wfile.write(frame)
                return

            self.send_response(200)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()

            frame_interval = max(0.03, 1.0 / max(config.fps, 1.0))
            while True:
                frame = camera.read_jpeg()
                try:
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                    time.sleep(frame_interval)
                except (BrokenPipeError, ConnectionResetError):
                    break

    return Handler


def parse_args() -> CameraConfig:
    parser = argparse.ArgumentParser(description="Minimal MJPEG camera server for iCar Web vision page.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=float, default=12.0)
    parser.add_argument("--quality", type=int, default=75)
    args = parser.parse_args()
    return CameraConfig(
        host=args.host,
        port=args.port,
        device=args.device,
        width=args.width,
        height=args.height,
        fps=args.fps,
        quality=max(30, min(95, args.quality)),
    )


def main() -> None:
    config = parse_args()
    camera = CameraSource(config)
    server = ThreadedHttpServer((config.host, config.port), build_handler(camera, config))
    print(f"iCar camera MJPEG server listening on {config.host}:{config.port}, status={camera.status()}", flush=True)
    try:
        server.serve_forever()
    finally:
        camera.close()
        server.server_close()


if __name__ == "__main__":
    main()
