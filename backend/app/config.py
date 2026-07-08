from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    frontend_dir: str = "frontend"


@dataclass
class CarConfig:
    adapter: str = "simulated"
    host: str = "172.20.10.3"
    port: int = 8888
    command_timeout_sec: float = 2.0
    cmd_vel_topic: str = "/cmd_vel"
    nav_goal_topic: str = "/goal_pose"
    nav_action: str = "/navigate_to_pose"
    command_map: dict[str, str] = field(default_factory=lambda: {
        "forward": "FORWARD {speed}\n",
        "backward": "BACKWARD {speed}\n",
        "left": "LEFT {speed}\n",
        "right": "RIGHT {speed}\n",
        "stop": "STOP\n",
        "emergency_stop": "ESTOP\n",
    })


@dataclass
class AppConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    car: CarConfig = field(default_factory=CarConfig)
    points_file: str = "config/points.json"
    routes_file: str = "config/routes.json"
    reports_dir: str = "data/reports"
    captures_dir: str = "data/captures"
    sensor_tick_sec: float = 1.5
    navigation_tick_sec: float = 0.8
    vision_tick_sec: float = 5.0


def _deep_update(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def _dataclass_to_dict(config: AppConfig) -> dict[str, Any]:
    return {
        "server": vars(config.server),
        "car": vars(config.car),
        "points_file": config.points_file,
        "routes_file": config.routes_file,
        "reports_dir": config.reports_dir,
        "captures_dir": config.captures_dir,
        "sensor_tick_sec": config.sensor_tick_sec,
        "navigation_tick_sec": config.navigation_tick_sec,
        "vision_tick_sec": config.vision_tick_sec,
    }


def _from_dict(data: dict[str, Any]) -> AppConfig:
    server = ServerConfig(**data.get("server", {}))
    car = CarConfig(**data.get("car", {}))
    return AppConfig(
        server=server,
        car=car,
        points_file=data.get("points_file", "config/points.json"),
        routes_file=data.get("routes_file", "config/routes.json"),
        reports_dir=data.get("reports_dir", "data/reports"),
        captures_dir=data.get("captures_dir", "data/captures"),
        sensor_tick_sec=float(data.get("sensor_tick_sec", 1.5)),
        navigation_tick_sec=float(data.get("navigation_tick_sec", 0.8)),
        vision_tick_sec=float(data.get("vision_tick_sec", 5.0)),
    )


def load_config() -> AppConfig:
    default = _dataclass_to_dict(AppConfig())
    config_path = Path(os.getenv("ICAR_CONFIG", CONFIG_DIR / "app.example.json"))
    if config_path.exists():
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
        default = _deep_update(default, loaded)

    default["car"]["adapter"] = os.getenv("ICAR_CAR_ADAPTER", default["car"]["adapter"])
    default["car"]["host"] = os.getenv("ICAR_CAR_HOST", default["car"]["host"])
    default["car"]["port"] = int(os.getenv("ICAR_CAR_PORT", default["car"]["port"]))
    default["server"]["host"] = os.getenv("ICAR_HOST", default["server"]["host"])
    default["server"]["port"] = int(os.getenv("ICAR_PORT", default["server"]["port"]))
    return _from_dict(default)


def resolve_project_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def read_json_file(path_value: str, fallback: Any) -> Any:
    path = resolve_project_path(path_value)
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))
