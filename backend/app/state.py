from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import AppConfig, read_json_file, resolve_project_path
from .database import DatabaseStore, NullDatabaseStore


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class StateHub:
    def __init__(self, config: AppConfig, database: DatabaseStore | None = None) -> None:
        self.config = config
        self.database = database or NullDatabaseStore()
        self.clients: set[Any] = set()
        self.points: list[dict[str, Any]] = read_json_file(config.points_file, [])
        self.routes: list[dict[str, Any]] = read_json_file(config.routes_file, [])
        self.robot: dict[str, Any] = {
            "connected": config.car.adapter == "simulated",
            "adapter": config.car.adapter,
            "mode": "standby",
            "battery": 86,
            "speed": 0,
            "pose": {"x": 1.2, "y": 1.2, "theta": 0},
            "target": None,
            "last_command": "none",
            "last_error": None,
            "updated_at": now_text(),
        }
        self.navigation: dict[str, Any] = {
            "task_id": None,
            "state": "idle",
            "target": None,
            "route": [],
            "route_index": 0,
            "progress": 0,
            "message": "等待任务",
            "started_at": None,
            "updated_at": now_text(),
        }
        self.sensors: dict[str, dict[str, Any]] = {
            "temperature": {"name": "temperature", "label": "温度", "value": 24.6, "unit": "C", "level": "normal"},
            "humidity": {"name": "humidity", "label": "湿度", "value": 48, "unit": "%", "level": "normal"},
            "light": {"name": "light", "label": "光照", "value": 420, "unit": "lx", "level": "normal"},
            "gas": {"name": "gas", "label": "可燃气体", "value": 0.08, "unit": "ppm", "level": "normal"},
            "pm25": {"name": "pm25", "label": "PM2.5", "value": 22, "unit": "ug/m3", "level": "normal"},
        }
        self.vision: list[dict[str, Any]] = []
        self.alarms: list[dict[str, Any]] = []
        self.reports: list[dict[str, Any]] = []
        resolve_project_path(config.reports_dir).mkdir(parents=True, exist_ok=True)
        resolve_project_path(config.captures_dir).mkdir(parents=True, exist_ok=True)

    async def register(self, websocket: Any) -> None:
        self.clients.add(websocket)
        await self.send_to(websocket, "snapshot", self.snapshot())

    def unregister(self, websocket: Any) -> None:
        self.clients.discard(websocket)

    async def send_to(self, websocket: Any, event_type: str, payload: Any) -> None:
        await websocket.send_text(json.dumps({"type": event_type, "payload": payload}, ensure_ascii=False))

    async def broadcast(self, event_type: str, payload: Any) -> None:
        if not self.clients:
            return
        message = json.dumps({"type": event_type, "payload": payload}, ensure_ascii=False)
        closed: list[Any] = []
        for client in list(self.clients):
            try:
                await client.send_text(message)
            except Exception:
                closed.append(client)
        for client in closed:
            self.unregister(client)

    def snapshot(self) -> dict[str, Any]:
        return {
            "robot": self.robot,
            "navigation": self.navigation,
            "points": self.points,
            "routes": self.routes,
            "sensors": list(self.sensors.values()),
            "vision": self.vision[:10],
            "alarms": self.alarms[:20],
            "reports": self.reports[:20],
        }

    async def update_robot(self, **changes: Any) -> None:
        self.robot.update(changes)
        self.robot["updated_at"] = now_text()
        await self.broadcast("robot_status", self.robot)

    async def update_navigation(self, **changes: Any) -> None:
        self.navigation.update(changes)
        self.navigation["updated_at"] = now_text()
        await self.broadcast("navigation_status", self.navigation)

    async def update_sensor(self, name: str, data: dict[str, Any]) -> None:
        current = self.sensors.get(name, {})
        current.update(data)
        current["updated_at"] = now_text()
        self.sensors[name] = current
        self.database.save_sensor_sample(current)
        await self.broadcast("sensor_update", current)

    async def add_vision_event(self, event: dict[str, Any]) -> None:
        event = {"id": f"vis-{uuid.uuid4().hex[:8]}", "timestamp": now_text(), **event}
        self.vision.insert(0, event)
        self.vision = self.vision[:50]
        self.database.save_vision_event(event)
        await self.broadcast("vision_event", event)

    async def add_alarm(self, alarm_type: str, level: str, message: str, source: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        alarm = {
            "alarm_id": f"alm-{uuid.uuid4().hex[:8]}",
            "type": alarm_type,
            "level": level,
            "message": message,
            "source": source,
            "status": "open",
            "timestamp": now_text(),
            "metadata": metadata or {},
        }
        self.alarms.insert(0, alarm)
        self.alarms = self.alarms[:100]
        self.database.save_alarm(alarm)
        await self.broadcast("alarm_event", alarm)
        return alarm

    async def confirm_alarm(self, alarm_id: str, operator: str = "web") -> dict[str, Any] | None:
        for alarm in self.alarms:
            if alarm["alarm_id"] == alarm_id:
                alarm["status"] = "confirmed"
                alarm["confirmed_by"] = operator
                alarm["confirmed_at"] = now_text()
                self.database.save_alarm(alarm)
                await self.broadcast("alarm_update", alarm)
                return alarm
        return None

    async def add_report(self, title: str, summary: str, details: dict[str, Any]) -> dict[str, Any]:
        report = {
            "report_id": f"rep-{uuid.uuid4().hex[:8]}",
            "title": title,
            "summary": summary,
            "details": details,
            "timestamp": now_text(),
        }
        self.reports.insert(0, report)
        self.reports = self.reports[:50]
        await self._persist_report(report)
        self.database.save_report(report)
        await self.broadcast("report_created", report)
        return report

    async def _persist_report(self, report: dict[str, Any]) -> None:
        reports_dir = resolve_project_path(self.config.reports_dir)
        reports_dir.mkdir(parents=True, exist_ok=True)
        path = reports_dir / f"{report['report_id']}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def point_by_id(self, point_id: str) -> dict[str, Any] | None:
        return next((point for point in self.points if point.get("id") == point_id), None)

    def route_by_id(self, route_id: str) -> dict[str, Any] | None:
        return next((route for route in self.routes if route.get("id") == route_id), None)
