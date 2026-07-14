from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
DOTENV_PATH = PROJECT_ROOT / ".env"
PARENT_DOTENV_PATH = PROJECT_ROOT.parent / ".env"


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    frontend_dir: str = "frontend"


@dataclass
class CarConfig:
    adapter: str = "simulated"
    host: str = "172.20.10.3"
    port: int = 6001
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
class DatabaseConfig:
    enabled: bool = False
    host: str = ""
    port: int = 3306
    user: str = "root"
    password: str = ""
    database: str = "icar"
    charset: str = "utf8mb4"
    connect_timeout_sec: int = 5


@dataclass
class VisionConfig:
    mode: str = "auto"
    service_host: str = ""
    service_port: int = 8765
    service_base_url: str = ""
    detect_path: str = "/detect"
    health_path: str = "/health"
    stream_url: str = ""
    request_timeout_sec: float = 8.0
    hazard_enabled: bool = False
    hazard_yolo_root: str = ""
    hazard_weights: str = ""
    hazard_data: str = ""
    hazard_conf: float = 0.25
    hazard_labels: list[str] = field(default_factory=lambda: ["smoke", "fire"])


@dataclass
class MotionConfig:
    container_name: str = "icar_free_roam"
    image_name: str = "icar/ros-foxy:1.0.2"
    robot_type: str = "x3"
    rplidar_type: str = "a1"
    host_icar_ws: str = "/home/jetson/temp/icar_ros2_ws/icar_ws"
    host_library_ws: str = "/home/jetson/code/software/library_ws"
    container_icar_ws: str = "/root/icar_ros2_ws/temp/icar_ros2_ws/icar_ws"
    container_library_ws: str = "/root/library_ws"
    lock_file: str = "/tmp/icar-motion.lock"
    lease_file: str = "/tmp/icar-motion-lease.json"
    supervisor_pid_file: str = "/tmp/icar-motion-supervisor.pid"
    supervisor_log: str = "/tmp/icar-motion-supervisor.log"
    driver_node: str = "Mcnamu_driver_X3"
    driver_package: str = "icar_bringup"
    lidar_launch_package: str = "sllidar_ros2"
    lidar_launch_file: str = "sllidar_launch.py"
    avoidance_node: str = "laser_Avoidance_a1_X3"
    avoidance_package: str = "icar_laser"
    default_linear: float = 0.08
    default_angular: float = 0.30
    app_path_glob: str = "*/Rosmaster-App/rosmaster/app.py*"
    bridge_path_glob: str = "*/icar_rosmaster_tcp_bridge.py*"
    zero_vel_dwell_sec: float = 2.0
    health_poll_interval_sec: float = 2.5
    health_failure_threshold: int = 2
    ssh_timeout_sec: float = 10.0


@dataclass
class AppConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    car: CarConfig = field(default_factory=CarConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    motion: MotionConfig = field(default_factory=MotionConfig)
    points_file: str = "config/points.json"
    routes_file: str = "config/routes.json"
    reports_dir: str = "data/reports"
    captures_dir: str = "data/captures"
    sensor_tick_sec: float = 1.5
    navigation_tick_sec: float = 0.8
    vision_tick_sec: float = 3.0


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
        "database": vars(config.database),
        "vision": vars(config.vision),
        "motion": vars(config.motion),
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
    database = DatabaseConfig(**data.get("database", {}))
    vision = VisionConfig(**data.get("vision", {}))
    motion = MotionConfig(**data.get("motion", {}))
    return AppConfig(
        server=server,
        car=car,
        database=database,
        vision=vision,
        motion=motion,
        points_file=data.get("points_file", "config/points.json"),
        routes_file=data.get("routes_file", "config/routes.json"),
        reports_dir=data.get("reports_dir", "data/reports"),
        captures_dir=data.get("captures_dir", "data/captures"),
        sensor_tick_sec=float(data.get("sensor_tick_sec", 1.5)),
        navigation_tick_sec=float(data.get("navigation_tick_sec", 0.8)),
        vision_tick_sec=float(data.get("vision_tick_sec", 3.0)),
    )


def _load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value


def load_config() -> AppConfig:
    _load_dotenv(DOTENV_PATH)
    _load_dotenv(PARENT_DOTENV_PATH)
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
    default["vision"]["mode"] = os.getenv("ICAR_VISION_MODE", default["vision"]["mode"])
    default["vision"]["service_host"] = os.getenv("ICAR_VISION_HOST", default["vision"]["service_host"])
    default["vision"]["service_port"] = int(os.getenv("ICAR_VISION_PORT", default["vision"]["service_port"]))
    default["vision"]["service_base_url"] = os.getenv("ICAR_VISION_BASE_URL", default["vision"]["service_base_url"])
    default["vision"]["stream_url"] = os.getenv("ICAR_VISION_STREAM_URL", default["vision"]["stream_url"])
    default["vision"]["hazard_enabled"] = os.getenv(
        "ICAR_HAZARD_VISION_ENABLED",
        str(default["vision"]["hazard_enabled"]),
    ).lower() in {"1", "true", "yes", "on"}
    default["vision"]["hazard_yolo_root"] = os.getenv("ICAR_HAZARD_YOLO_ROOT", default["vision"]["hazard_yolo_root"])
    default["vision"]["hazard_weights"] = os.getenv("ICAR_HAZARD_WEIGHTS", default["vision"]["hazard_weights"])
    default["vision"]["hazard_data"] = os.getenv("ICAR_HAZARD_DATA", default["vision"]["hazard_data"])
    default["vision"]["hazard_conf"] = float(os.getenv("ICAR_HAZARD_CONF", default["vision"]["hazard_conf"]))
    hazard_labels = os.getenv("ICAR_HAZARD_LABELS")
    if hazard_labels:
        default["vision"]["hazard_labels"] = [item.strip().lower() for item in hazard_labels.split(",") if item.strip()]
    default["vision_tick_sec"] = float(os.getenv("ICAR_VISION_TICK_SEC", default["vision_tick_sec"]))
    if os.getenv("ICAR_DB_HOST"):
        default["database"]["enabled"] = True
        default["database"]["host"] = os.getenv("ICAR_DB_HOST", default["database"]["host"])
        default["database"]["port"] = int(os.getenv("ICAR_DB_PORT", default["database"]["port"]))
        default["database"]["user"] = os.getenv("ICAR_DB_USER", default["database"]["user"])
        default["database"]["password"] = os.getenv("ICAR_DB_PASSWORD", default["database"]["password"])
        default["database"]["database"] = os.getenv("ICAR_DB_NAME", default["database"]["database"])
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
