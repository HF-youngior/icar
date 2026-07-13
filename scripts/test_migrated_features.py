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
    if light != "$000508010100000F#":
        raise AssertionError(f"unexpected light frame: {light}")
    light_frames = adapter._auxiliary_payloads("light", enabled=True, r=38, g=244, b=255)
    if light_frames[:2] != ["$000508010100000F#", "$0105080101000010#"]:
        raise AssertionError(f"unexpected light frames: {light_frames}")
    if "$0130080026F4FF52#" not in light_frames:
        raise AssertionError(f"missing legacy light frames: {light_frames}")
    if "$0320080026F4FF44#" not in light_frames:
        raise AssertionError(f"missing app-compatible light frame: {light_frames}")


def check_api() -> None:
    with TestClient(app) as client:
        health = client.get("/api/health")
        if health.status_code != 200 or not health.json().get("ok"):
            raise AssertionError(f"health failed: {health.text}")
        if health.json().get("ui_version") != "slam-navigation-v3":
            raise AssertionError(f"unexpected UI version: {health.text}")

        navigation_page = client.get("/navigation")
        page_text = navigation_page.text
        if navigation_page.status_code != 200 or "SLAM Navigation v3" not in page_text:
            raise AssertionError("navigation page is not the SLAM v3 page")
        for marker in ("点选当前位置/起点", "点选目标点", "建图遥控器"):
            if marker not in page_text:
                raise AssertionError(f"navigation page missing marker: {marker}")
        if "房间导航与巡逻" in page_text or "家庭地图" in page_text:
            raise AssertionError("navigation page still contains the old simulated navigation UI")
        if "no-store" not in navigation_page.headers.get("cache-control", ""):
            raise AssertionError("navigation page should disable browser cache")

        control_page = client.get("/control")
        control_text = control_page.text
        for marker in ("voicePlayBtn", "主人，我在"):
            if control_page.status_code != 200 or marker not in control_text:
                raise AssertionError(f"control voice UI missing marker: {marker}")

        cruise_page = client.get("/cruise")
        cruise_text = cruise_page.text
        for marker in ("cruiseCanvas", "cruiseSaveWaypointBtn", "cruiseSaveRouteBtn", "cruisePlanBtn", "cruiseStartBtn"):
            if cruise_page.status_code != 200 or marker not in cruise_text:
                raise AssertionError(f"cruise UI missing marker: {marker}")
        cruise_plan = client.post(
            "/api/cruise/plan",
            json={
                "grid": {"width": 12, "height": 12},
                "start_heading": "east",
                "waypoints": [
                    {"id": "a", "name": "A", "x": 1, "y": 1},
                    {"id": "b", "name": "B", "x": 6, "y": 1},
                    {"id": "c", "name": "C", "x": 6, "y": 5},
                ],
            },
        )
        if cruise_plan.status_code != 200 or cruise_plan.json().get("totals", {}).get("segments") != 4:
            raise AssertionError(f"cruise plan failed: {cruise_plan.text}")
        route_save = client.post(
            "/api/cruise/routes",
            json={
                "name": "路线1",
                "route": {
                    "grid": {"width": 12, "height": 12},
                    "waypoints": [
                        {"id": "a", "name": "书房", "x": 1, "y": 1},
                        {"id": "b", "name": "卧室", "x": 6, "y": 1},
                        {"id": "c", "name": "客厅", "x": 6, "y": 5},
                    ],
                    "plan": cruise_plan.json(),
                },
            },
        )
        if route_save.status_code != 200 or not route_save.json().get("ok"):
            raise AssertionError(f"cruise route save failed: {route_save.text}")
        route_list = client.get("/api/cruise/routes")
        if route_list.status_code != 200 or not route_list.json().get("routes"):
            raise AssertionError(f"cruise route list failed: {route_list.text}")

        camera = client.get("/api/camera/candidates")
        camera_body = camera.json()
        labels = [item.get("label") for item in camera_body.get("urls", [])]
        if camera.status_code != 200 or labels[:2] != ["原生 App 实时画面（默认）", "自建摄像头 8080（备用）"]:
            raise AssertionError(f"camera candidates failed: {camera.text}")

        vision_page = client.get("/vision")
        vision_text = vision_page.text
        for marker in ("gestureToggleBtn", "gestureSpeedInput", "gestureCanvas", "/assets/vendor/mediapipe/hands/hands.js"):
            if vision_page.status_code != 200 or marker not in vision_text:
                raise AssertionError(f"vision gesture UI missing marker: {marker}")

        manual = client.post("/api/control/manual", json={"direction": "forward", "speed": 0.16})
        if manual.status_code != 200 or not manual.json().get("ok"):
            raise AssertionError(f"manual failed: {manual.text}")

        aux = client.post("/api/control/aux", json={"action": "buzzer", "duration_ms": 300})
        if aux.status_code != 200 or not aux.json().get("ok"):
            raise AssertionError(f"aux failed: {aux.text}")

        voice = client.post("/api/control/aux", json={"action": "voice", "text": "主人，我在", "volume_percent": 85})
        if voice.status_code != 200 or not voice.json().get("ok"):
            raise AssertionError(f"voice aux failed: {voice.text}")

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

    amcl_text = """
pose:
  pose:
    position:
      x: 1.2
      y: -0.4
      z: 0.0
    orientation:
      x: 0.0
      y: 0.0
      z: 0.70682518
      w: 0.70738827
  covariance:
  - 0.0
"""
    parsed = manager._parse_amcl_pose(amcl_text)
    if round(parsed["x"], 2) != 1.20 or round(parsed["y"], 2) != -0.40 or not 1.56 < parsed["theta"] < 1.58:
        raise AssertionError(f"unexpected AMCL pose parse: {parsed}")

    if manager._parse_action_server_count("Action servers: 1\n    /bt_navigator") != 1:
        raise AssertionError("Nav2 action server parser failed")
    nav2_failure = manager._nav2_failure_message("[ERROR] [bt_navigator-7]: process has died [pid 1, exit code -11]")
    if "bt_navigator" not in nav2_failure:
        raise AssertionError("Nav2 bt_navigator crash parser failed")

    tiny_pgm = b"P5\n2 2\n255\n\x00\x7f\xff\x40"
    png, width, height = manager._pgm_to_png(tiny_pgm)
    if width != 2 or height != 2 or not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AssertionError("PGM to PNG conversion failed")


def main() -> None:
    check_tcp_frames()
    check_slam_helpers()
    check_api()
    print("Migrated feature test passed.")
    print("Checked: camera candidates, speed TCP frames, light, buzzer, follow-line, cruise planner, SLAM helpers.")


if __name__ == "__main__":
    main()
