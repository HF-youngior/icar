from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .adapters.factory import build_adapter
from .config import PROJECT_ROOT, load_config, resolve_project_path
from .database import DatabaseStore
from .navigation import NavigationService
from .sensors import SensorService
from .state import StateHub
from .vision import VisionService


config = load_config()
logger = logging.getLogger(__name__)
database = DatabaseStore(config.database)
state = StateHub(config, database)
adapter = build_adapter(config)
navigation = NavigationService(config, state, adapter)
sensors = SensorService(config, state)
vision = VisionService(config, state)

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
    try:
        await adapter.connect()
        await state.update_robot(connected=True, adapter=adapter.name, mode="standby", last_error=None)
        return {"ok": True, "adapter": adapter.name}
    except Exception as exc:
        logger.exception("car reconnect failed")
        await state.update_robot(connected=False, adapter=adapter.name, mode="offline", last_error=str(exc))
        await state.add_alarm("connection", "warning", f"小车连接失败：{exc}", "backend")
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/snapshot")
async def snapshot() -> dict[str, Any]:
    return state.snapshot()


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
    if direction not in {"forward", "backward", "left", "right", "stop"}:
        raise HTTPException(status_code=400, detail="Unsupported direction")
    try:
        result = await adapter.stop() if direction == "stop" else await adapter.manual_control(direction, speed)
        await state.update_robot(
            connected=True,
            mode="manual" if direction != "stop" else "standby",
            speed=0 if direction == "stop" else speed,
            last_command=direction,
            last_error=None,
        )
        return result
    except Exception as exc:
        logger.exception("manual control failed: direction=%s speed=%s", direction, speed)
        await state.update_robot(connected=False, mode="offline", last_error=str(exc))
        await state.add_alarm("manual_control", "warning", f"控制指令失败：{exc}", "backend")
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
