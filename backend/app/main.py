from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request as UrlRequest, urlopen

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .adapters.factory import build_adapter
from .car_runtime import CarRuntimeRecovery
from .config import PROJECT_ROOT, load_config, resolve_project_path
from .database import DatabaseStore
from .navigation import NavigationService
from .sensors import SensorService
from .slam_runtime import SlamRuntimeManager
from .state import StateHub
from .vision import VisionService


config = load_config()
logger = logging.getLogger(__name__)
database = DatabaseStore(config.database)
state = StateHub(config, database)
adapter = build_adapter(config)
runtime = CarRuntimeRecovery(config)
navigation = NavigationService(config, state, adapter)
sensors = SensorService(config, state)
vision = VisionService(config, state)
slam_runtime = SlamRuntimeManager(config)
manual_control_lock = asyncio.Lock()

app = FastAPI(title="智能家居管家机器人平台", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_dir = resolve_project_path(config.server.frontend_dir)
assets_dir = frontend_dir / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.on_event("startup")
async def on_startup() -> None:
    database.init_schema()
    navigation.start_background()
    sensors.start_background()
    vision.start_background()
    try:
        await adapter.connect()
        await state.update_robot(connected=True, adapter=adapter.name, mode="standby")
    except Exception as exc:
        logger.exception("car connect failed during startup")
        await state.update_robot(connected=False, adapter=adapter.name, mode="offline")
        await state.add_alarm("connection", "warning", f"小车连接失败：{exc}", "backend")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(frontend_dir / "index.html")


@app.get("/dashboard")
async def dashboard_page() -> FileResponse:
    return FileResponse(frontend_dir / "index.html")


@app.get("/control")
async def control_page() -> FileResponse:
    return FileResponse(frontend_dir / "control.html")


@app.get("/navigation")
async def navigation_page() -> FileResponse:
    return FileResponse(frontend_dir / "navigation.html")


@app.get("/vision")
async def vision_page() -> FileResponse:
    return FileResponse(frontend_dir / "vision.html")


@app.get("/alarms")
async def alarms_page() -> FileResponse:
    return FileResponse(frontend_dir / "alarms.html")


@app.get("/reports")
async def reports_page() -> FileResponse:
    return FileResponse(frontend_dir / "reports.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "adapter": adapter.name, "project_root": str(PROJECT_ROOT)}


@app.get("/api/db/health")
async def db_health() -> dict[str, Any]:
    return database.health()


@app.post("/api/car/reconnect")
async def car_reconnect() -> dict[str, Any]:
    recovery: dict[str, Any] | None = None
    try:
        if config.car.adapter == "tcp":
            recovery = await asyncio.to_thread(runtime.recover_builtin_app)
        await adapter.connect()
        await state.update_robot(
            connected=True,
            adapter=adapter.name,
            mode="standby",
            last_error=None,
            last_command="reconnect",
        )
        return {"ok": True, "adapter": adapter.name, "runtime": recovery}
    except Exception as exc:
        logger.exception("car reconnect failed")
        detail = str(exc) or "car control port is not reachable"
        if recovery and recovery.get("error"):
            detail = f"{detail}; {recovery['error']}"
        await state.update_robot(connected=False, adapter=adapter.name, mode="offline", last_error=detail)
        await state.add_alarm("connection", "warning", f"小车连接失败：{detail}", "backend")
        raise HTTPException(status_code=503, detail={"error": detail, "runtime": recovery}) from exc


@app.get("/api/car/runtime")
async def car_runtime() -> dict[str, Any]:
    return {"ok": True, "host": config.car.host, "ports": await asyncio.to_thread(runtime.check_ports)}


@app.get("/api/snapshot")
async def snapshot() -> dict[str, Any]:
    return state.snapshot()


@app.get("/api/camera/candidates")
async def camera_candidates(host: str | None = None) -> dict[str, Any]:
    target_host = (host or config.car.host).strip()
    def proxied(port: int, path: str) -> str:
        return f"/api/camera/stream?host={quote(target_host)}&port={port}&path={quote(path, safe='')}"

    urls = [
        {"label": "原生 App 实时画面（默认）", "url": f"http://{target_host}:6500/video_feed"},
        {"label": "自建摄像头 8080（备用）", "url": f"http://{target_host}:8080/?action=stream"},
        {"label": "原生 App 6500（后端代理）", "url": proxied(6500, "/video_feed")},
        {"label": "自建摄像头 8080（后端代理）", "url": proxied(8080, "/?action=stream")},
    ]
    return {
        "ok": True,
        "host": target_host,
        "urls": urls,
    }


@app.get("/api/camera/stream")
def camera_stream(host: str | None = None, port: int = 8080, path: str = "/?action=stream") -> StreamingResponse:
    target_host = (host or config.car.host).strip()
    if not target_host:
        raise HTTPException(status_code=400, detail="Camera host is empty")
    if port not in {6500, 8080, 8081}:
        raise HTTPException(status_code=400, detail="Unsupported camera port")
    target_path = path if path.startswith("/") else f"/{path}"
    if "://" in target_path or "\r" in target_path or "\n" in target_path:
        raise HTTPException(status_code=400, detail="Unsupported camera path")
    target_url = f"http://{target_host}:{port}{target_path}"

    try:
        request = UrlRequest(target_url, headers={"User-Agent": "iCar-Web/1.0"})
        upstream = urlopen(request, timeout=8)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        logger.warning("camera proxy failed before streaming: %s -> %s", target_url, exc)
        raise HTTPException(status_code=502, detail=f"Camera stream unavailable: {target_url}") from exc

    def generate():
        try:
            with upstream:
                while True:
                    chunk = upstream.read(8192)
                    if not chunk:
                        break
                    yield chunk
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            logger.warning("camera proxy failed: %s -> %s", target_url, exc)
            return

    media_type = upstream.headers.get("Content-Type") or (
        "image/jpeg" if target_path.startswith("/snapshot") else "multipart/x-mixed-replace; boundary=frame"
    )
    return StreamingResponse(generate(), media_type=media_type, headers={"Cache-Control": "no-cache"})


@app.get("/api/camera/health")
def camera_health(host: str | None = None, port: int = 8080) -> dict[str, Any]:
    target_host = (host or config.car.host).strip()
    target_url = f"http://{target_host}:{port}/health"
    try:
        request = UrlRequest(target_url, headers={"User-Agent": "iCar-Web/1.0"})
        with urlopen(request, timeout=3) as response:
            body = response.read(200).decode("utf-8", errors="replace")
        return {"ok": True, "url": target_url, "body": body}
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "url": target_url, "error": str(exc)}


@app.get("/api/camera/direct-candidates")
async def camera_direct_candidates(host: str | None = None) -> dict[str, Any]:
    target_host = (host or config.car.host).strip()
    paths = [
        ("iCar Camera Bridge 8080", 8080, "/?action=stream"),
        ("iCar Camera Bridge MJPEG", 8080, "/stream.mjpg"),
        ("Camera 6500", 6500, "/?action=stream"),
        ("Depth 6500", 6500, "/depth_stream"),
        ("USB 6500", 6500, "/usb_stream"),
        ("Wide 6500", 6500, "/wide_angle_stream"),
        ("MJPEG 6500", 6500, "/stream.mjpg"),
        ("Camera 8081", 8081, "/?action=stream"),
    ]
    return {
        "ok": True,
        "host": target_host,
        "urls": [
            {"label": label, "url": f"http://{target_host}:{port}{path}"}
            for label, port, path in paths
        ],
    }


@app.get("/api/points")
async def points() -> list[dict[str, Any]]:
    return state.points


@app.get("/api/routes")
async def routes() -> list[dict[str, Any]]:
    return state.routes


@app.get("/api/reports")
async def reports() -> list[dict[str, Any]]:
    return state.reports


@app.post("/api/control/manual")
async def manual_control(payload: dict[str, Any]) -> dict[str, Any]:
    direction = str(payload.get("direction", "")).lower()
    speed = float(payload.get("speed", 0.16))
    pulse_ms = max(80, min(1000, int(payload.get("duration_ms", 260))))
    if direction not in {"forward", "backward", "left", "right", "stop"}:
        raise HTTPException(status_code=400, detail="Unsupported direction")
    try:
        async with manual_control_lock:
            if direction == "stop":
                result = await adapter.stop()
            else:
                result = await adapter.manual_control(direction, speed)
                await asyncio.sleep(pulse_ms / 1000)
                result["stop"] = await adapter.stop()
                result["pulse_ms"] = pulse_ms
        await state.update_robot(
            connected=True,
            mode="standby",
            speed=0,
            last_command=direction if direction == "stop" else f"{direction}_pulse",
            last_error=None,
        )
        return result
    except Exception as exc:
        logger.exception("manual control failed: direction=%s speed=%s", direction, speed)
        await state.update_robot(connected=False, mode="offline", last_error=str(exc))
        await state.add_alarm("manual_control", "warning", f"控制指令失败：{exc}", "backend")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/control/aux")
async def auxiliary_control(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action", "")).lower()
    if action not in {"light", "buzzer", "follow_line"}:
        raise HTTPException(status_code=400, detail="Unsupported auxiliary action")
    try:
        values = {key: value for key, value in payload.items() if key != "action"}
        result = await adapter.auxiliary_control(action, **values)
        await state.update_robot(
            connected=True,
            last_command=f"aux:{action}",
            last_error=None,
        )
        return result
    except Exception as exc:
        logger.exception("auxiliary control failed: action=%s payload=%s", action, payload)
        await state.update_robot(connected=False, mode="offline", last_error=str(exc))
        await state.add_alarm("auxiliary_control", "warning", f"auxiliary control failed: {exc}", "backend")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/control/emergency-stop")
async def emergency_stop(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    reason = (payload or {}).get("reason", "web")
    await navigation.emergency_stop(str(reason))
    return {"ok": True}


@app.post("/api/navigation/goal")
async def navigation_goal(payload: dict[str, Any]) -> dict[str, Any]:
    point_id = str(payload.get("point_id", ""))
    try:
        return await navigation.go_to(point_id)
    except Exception as exc:
        await state.add_alarm("navigation", "warning", f"导航启动失败：{exc}", "backend")
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/navigation/patrol")
async def navigation_patrol(payload: dict[str, Any]) -> dict[str, Any]:
    route_id = str(payload.get("route_id", ""))
    try:
        return await navigation.start_patrol(route_id)
    except Exception as exc:
        await state.add_alarm("patrol", "warning", f"巡逻启动失败：{exc}", "backend")
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/navigation/stop")
async def navigation_stop() -> dict[str, Any]:
    await navigation.stop()
    return {"ok": True}


@app.get("/api/slam/status")
async def slam_status() -> dict[str, Any]:
    return await asyncio.to_thread(slam_runtime.status)


@app.get("/api/slam/maps")
async def slam_maps() -> dict[str, Any]:
    return {"ok": True, "maps": await asyncio.to_thread(slam_runtime.list_maps)}


@app.get("/api/slam/maps/{map_name}/image")
async def slam_map_image(map_name: str) -> FileResponse:
    try:
        path = await asyncio.to_thread(slam_runtime.map_image_path, map_name)
        return FileResponse(path, media_type="image/png")
    except Exception as exc:
        logger.exception("slam map image failed: %s", map_name)
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/slam/logs")
async def slam_logs() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(slam_runtime.logs)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/slam/mapping/start")
async def slam_start_mapping(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    algorithm = str((payload or {}).get("algorithm", "gmapping")).lower()
    try:
        result = await asyncio.to_thread(slam_runtime.start_mapping, algorithm)
        await state.update_navigation(
            state="mapping",
            progress=0,
            message=f"SLAM 建图已启动：{algorithm}",
            target=None,
            route=[],
        )
        await state.update_robot(mode="mapping", last_command=f"slam_mapping:{algorithm}", last_error=None)
        return result
    except Exception as exc:
        logger.exception("slam mapping start failed")
        await state.add_alarm("slam", "warning", f"SLAM 建图启动失败：{exc}", "backend")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/slam/map/save")
async def slam_save_map(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    map_name = str((payload or {}).get("map_name", "yahboomcar_web"))
    try:
        result = await asyncio.to_thread(slam_runtime.save_map, map_name)
        await state.update_navigation(message=f"地图保存完成：{result.get('map')}", progress=1)
        return result
    except Exception as exc:
        logger.exception("slam map save failed")
        await state.add_alarm("slam", "warning", f"SLAM 地图保存失败：{exc}", "backend")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/slam/navigation/start")
async def slam_start_navigation(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = payload or {}
    algorithm = str(body.get("algorithm", "dwa")).lower()
    map_name = str(body.get("map", "yahboomcar.yaml"))
    try:
        result = await asyncio.to_thread(slam_runtime.start_navigation, algorithm, map_name)
        await state.update_navigation(
            state="nav_ready",
            progress=0,
            message=f"导航系统已启动：{algorithm.upper()} / {map_name}",
            target=None,
            route=[],
        )
        await state.update_robot(mode="navigation_ready", last_command=f"slam_nav:{algorithm}", last_error=None)
        return result
    except Exception as exc:
        logger.exception("slam navigation start failed")
        await state.add_alarm("slam", "warning", f"导航系统启动失败：{exc}", "backend")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/slam/pose/initial")
async def slam_initial_pose(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        x = float(payload.get("x", 0))
        y = float(payload.get("y", 0))
        theta = float(payload.get("theta", 0))
        result = await asyncio.to_thread(slam_runtime.send_initial_pose, x, y, theta)
        await state.update_robot(pose={"x": x, "y": y, "theta": theta}, last_command="slam_initial_pose", last_error=None)
        await state.update_navigation(message=f"初始位姿已设置：({x:.2f}, {y:.2f})")
        return result
    except Exception as exc:
        logger.exception("slam initial pose failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/slam/goal")
async def slam_goal(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        x = float(payload.get("x", 0))
        y = float(payload.get("y", 0))
        theta = float(payload.get("theta", 0))
        result = await asyncio.to_thread(slam_runtime.send_goal_pose, x, y, theta)
        await state.update_navigation(
            state="running",
            target={"id": "slam_goal", "name": "Web 目标点", "pose": {"x": x, "y": y, "theta": theta}},
            progress=0,
            message=f"已发送导航目标：({x:.2f}, {y:.2f})",
        )
        await state.update_robot(mode="navigation", target="Web 目标点", last_command="slam_goal", last_error=None)
        return result
    except Exception as exc:
        logger.exception("slam goal failed")
        await state.add_alarm("slam", "warning", f"导航目标发送失败：{exc}", "backend")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/slam/stop")
async def slam_stop() -> dict[str, Any]:
    try:
        result = await asyncio.to_thread(slam_runtime.stop)
        await navigation.stop(state="stopped", message="SLAM/导航进程已停止")
        return result
    except Exception as exc:
        logger.exception("slam stop failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/vision/detect")
async def vision_detect() -> dict[str, Any]:
    return await vision.detect_once()


@app.post("/api/alarms/{alarm_id}/confirm")
async def alarm_confirm(alarm_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    alarm = await state.confirm_alarm(alarm_id, (payload or {}).get("operator", "web"))
    if not alarm:
        raise HTTPException(status_code=404, detail="Alarm not found")
    return alarm


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    await state.register(websocket)
    try:
        while True:
            message = await websocket.receive_json()
            await handle_ws_message(message)
    except WebSocketDisconnect:
        state.unregister(websocket)


async def handle_ws_message(message: dict[str, Any]) -> None:
    msg_type = message.get("type")
    payload = message.get("payload") or {}
    if msg_type == "manual_control":
        await manual_control(payload)
    elif msg_type == "emergency_stop":
        await emergency_stop(payload)
    elif msg_type == "aux_control":
        await auxiliary_control(payload)
    elif msg_type == "nav_goal":
        await navigation_goal(payload)
    elif msg_type == "patrol_start":
        await navigation_patrol(payload)
    elif msg_type == "task_stop":
        await navigation_stop()
    elif msg_type == "vision_detect":
        await vision_detect()
    elif msg_type == "alarm_confirm":
        alarm_id = payload.get("alarm_id")
        if alarm_id:
            await alarm_confirm(str(alarm_id), payload)
    elif msg_type == "ping":
        await state.broadcast("pong", {"ok": True})
