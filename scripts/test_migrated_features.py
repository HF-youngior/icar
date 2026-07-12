from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / ".vendor"))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

os.environ["ICAR_CAR_ADAPTER"] = "simulated"
for key in ("ICAR_DB_HOST", "ICAR_DB_PORT", "ICAR_DB_USER", "ICAR_DB_PASSWORD", "ICAR_DB_NAME"):
    os.environ.pop(key, None)

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.config import CarConfig, load_config  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.adapters.tcp_car import TcpCarAdapter  # noqa: E402
from backend.app.slam_runtime import SlamRuntimeManager  # noqa: E402


def check_tcp_frames() -> None:
    adapter = TcpCarAdapter(CarConfig(adapter="tcp", host="127.0.0.1", port=9))

    movement = adapter._command_payloads("forward", speed=0.16)
    if movement != ["$011606323281#", "$011504011B#"]:
        raise AssertionError(f"unexpected forward frames: {movement}")

    follow = adapter._auxiliary_payload("follow_line", enabled=True)
    if follow != "$01630266#":
        raise AssertionError(f"unexpected follow-line frame: {follow}")

    buzzer = adapter._auxiliary_payload("buzzer", duration_ms=300)
    if buzzer != "$011306011E39#":
        raise AssertionError(f"unexpected buzzer frame: {buzzer}")

    light = adapter._auxiliary_payload("light", enabled=True, r=38, g=244, b=255)
    if light != "$01300A0026F4FF54#":
        raise AssertionError(f"unexpected light frame: {light}")
    light_frames = adapter._auxiliary_payloads("light", enabled=True, r=38, g=244, b=255)
    if light_frames[:2] != ["$01300A0026F4FF54#", "$01300A0126F4FF55#"] or light_frames[-1] != "$013106015089#":
        raise AssertionError(f"unexpected light frames: {light_frames}")


def check_api() -> None:
    with TestClient(app) as client:
        health = client.get("/api/health")
        if health.status_code != 200 or not health.json().get("ok"):
            raise AssertionError(f"health failed: {health.text}")

        camera = client.get("/api/camera/candidates")
        camera_body = camera.json()
        labels = [item.get("label") for item in camera_body.get("urls", [])]
        if camera.status_code != 200 or labels[:2] != ["原生 App 实时画面（默认）", "自建摄像头 8080（备用）"]:
            raise AssertionError(f"camera candidates failed: {camera.text}")

        manual = client.post("/api/control/manual", json={"direction": "forward", "speed": 0.16})
        if manual.status_code != 200 or not manual.json().get("ok"):
            raise AssertionError(f"manual failed: {manual.text}")

        aux = client.post("/api/control/aux", json={"action": "buzzer", "duration_ms": 300})
        if aux.status_code != 200 or not aux.json().get("ok"):
            raise AssertionError(f"aux failed: {aux.text}")

        slam_status = client.get("/api/slam/status")
        if slam_status.status_code != 200 or "ports" not in slam_status.json():
            raise AssertionError(f"slam status failed: {slam_status.text}")


def check_slam_helpers() -> None:
    manager = SlamRuntimeManager(load_config())
    pose = manager._pose_stamped_message(1.2, -0.4, 1.57)
    if "/goal_pose" in pose or "frame_id: 'map'" not in pose or "x: 1.2000" not in pose:
        raise AssertionError(f"unexpected pose message: {pose}")

    initial = manager._initial_pose_message(1.2, -0.4, 1.57)
    if "covariance" not in initial or "0.25000000" not in initial:
        raise AssertionError(f"unexpected initial pose message: {initial}")

    tiny_pgm = b"P5\n2 2\n255\n\x00\x7f\xff\x40"
    png, width, height = manager._pgm_to_png(tiny_pgm)
    if width != 2 or height != 2 or not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AssertionError("PGM to PNG conversion failed")


def main() -> None:
    check_tcp_frames()
    check_slam_helpers()
    check_api()
    print("Migrated feature test passed.")
    print("Checked: camera candidates, speed TCP frames, light, buzzer, follow-line, SLAM helpers.")


if __name__ == "__main__":
    main()
