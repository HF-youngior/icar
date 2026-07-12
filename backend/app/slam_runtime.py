from __future__ import annotations

import base64
import json
import math
import re
import shlex
import socket
import struct
import subprocess
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import AppConfig, DATA_DIR


@dataclass
class CommandResult:
    ok: bool
    command: str
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


class SlamRuntimeManager:
    container_name = "icar_web_nav"
    image_name = "yahboomtechnology/ros-foxy:5.0.1"
    remote_maps_dir = "/home/jetson/code/yahboomcar_ws/src/yahboomcar_nav/maps"
    container_maps_dir = "/root/yahboomcar_ros2_ws/yahboomcar_ws/src/yahboomcar_nav/maps"

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.user = "jetson"
        self.password = "yahboom"
        self.host_key = "ssh-ed25519 255 SHA256:AJffjk3YWwStux7ZbdKdft3teC8b7Jsubuvv4zMYuD8"
        self.robot_type = "x3"
        self.rplidar_type = "a1"
        self.cache_dir = DATA_DIR / "slam_maps"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.last_mode = "idle"
        self.last_message = "SLAM runtime idle"
        self.last_updated = 0.0

    @property
    def host(self) -> str:
        return self.config.car.host

    @property
    def target(self) -> str:
        return f"{self.user}@{self.host}"

    def port_open(self, port: int, timeout_sec: float = 1.2) -> bool:
        try:
            with socket.create_connection((self.host, port), timeout=timeout_sec):
                return True
        except OSError:
            return False

    def status(self) -> dict[str, Any]:
        ssh_open = self.port_open(22)
        container = {"running": False, "name": self.container_name, "processes": ""}
        topics: list[str] = []
        if ssh_open:
            try:
                output = self._ssh(
                    f"docker inspect -f '{{{{.State.Running}}}}' {shlex.quote(self.container_name)} 2>/dev/null || true",
                    timeout_sec=4,
                ).stdout.strip()
                container["running"] = output == "true"
                if container["running"]:
                    processes = self._docker_exec(
                        "pgrep -af 'map_gmapping|map_cartographer|map_rtabmap|laser_bringup|navigation_dwa|navigation_teb|nav2|slam' || true",
                        timeout_sec=4,
                    ).stdout.strip()
                    container["processes"] = processes
                    topic_output = self._docker_exec(
                        f"{self._ros_setup()} && timeout 4s ros2 topic list || true",
                        timeout_sec=7,
                    ).stdout
                    topics = [line.strip() for line in topic_output.splitlines() if line.strip()]
            except RuntimeError as exc:
                self.last_message = str(exc)
        return {
            "ok": ssh_open,
            "host": self.host,
            "ports": {
                "ssh_22": ssh_open,
                "control_6000": self.port_open(6000),
                "camera_6500": self.port_open(6500),
                "backup_bridge_6001": self.port_open(6001),
            },
            "container": container,
            "topics": topics,
            "mode": self.last_mode,
            "message": self.last_message,
            "updated_at": self.last_updated,
        }

    def start_mapping(self, algorithm: str = "gmapping") -> dict[str, Any]:
        launch = {
            "gmapping": "map_gmapping_launch.py",
            "cartographer": "map_cartographer_launch.py",
            "rtabmap": "map_rtabmap_launch.py",
        }.get(algorithm)
        if not launch:
            raise ValueError(f"Unsupported mapping algorithm: {algorithm}")

        self.ensure_container()
        self._stop_ros_processes()
        self._docker_exec("pkill -f '[a]pp.py' || true", timeout_sec=4, tolerate=True)
        self._docker_exec_detached(
            f"/tmp/icar_slam_mapping_{algorithm}.log",
            f"ros2 launch yahboomcar_nav {launch}",
        )
        self.last_mode = "mapping"
        self.last_message = f"Started SLAM mapping with {algorithm}"
        self.last_updated = time.time()
        return {"ok": True, "mode": self.last_mode, "algorithm": algorithm, "log": f"/tmp/icar_slam_mapping_{algorithm}.log"}

    def save_map(self, map_name: str = "yahboomcar_web") -> dict[str, Any]:
        safe_name = self._sanitize_map_stem(map_name)
        self.ensure_container()
        container_path = f"{self.container_maps_dir}/{safe_name}"
        command = f"timeout 30s ros2 launch yahboomcar_nav save_map_launch.py map_path:={shlex.quote(container_path)}"
        result = self._docker_exec(f"{self._ros_setup()} && {command}", timeout_sec=36, tolerate=True)
        maps = self.list_maps(refresh_meta=False)
        ok = any(item["name"] == f"{safe_name}.yaml" for item in maps)
        self.last_message = f"Saved map {safe_name}" if ok else f"Map save command finished; verify {safe_name}.yaml"
        self.last_updated = time.time()
        return {
            "ok": ok,
            "map": f"{safe_name}.yaml",
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-2000:],
            "maps": maps,
        }

    def start_navigation(self, algorithm: str = "dwa", map_name: str = "yahboomcar.yaml") -> dict[str, Any]:
        launch = {
            "dwa": "navigation_dwa_launch.py",
            "teb": "navigation_teb_launch.py",
            "rtabmap": "navigation_rtabmap_launch.py",
        }.get(algorithm)
        if not launch:
            raise ValueError(f"Unsupported navigation algorithm: {algorithm}")
        safe_map = self._sanitize_map_file(map_name)
        container_map = f"{self.container_maps_dir}/{safe_map}"

        self.ensure_container()
        self._stop_ros_processes()
        self._docker_exec("pkill -f '[a]pp.py' || true", timeout_sec=4, tolerate=True)
        self._docker_exec_detached("/tmp/icar_slam_laser_bringup.log", "ros2 launch yahboomcar_nav laser_bringup_launch.py")
        time.sleep(4)
        self._docker_exec_detached(
            f"/tmp/icar_slam_navigation_{algorithm}.log",
            f"ros2 launch yahboomcar_nav {launch} map:={shlex.quote(container_map)}",
        )
        self.last_mode = "navigation"
        self.last_message = f"Started {algorithm.upper()} navigation with {safe_map}"
        self.last_updated = time.time()
        return {
            "ok": True,
            "mode": self.last_mode,
            "algorithm": algorithm,
            "map": safe_map,
            "logs": ["/tmp/icar_slam_laser_bringup.log", f"/tmp/icar_slam_navigation_{algorithm}.log"],
        }

    def stop(self) -> dict[str, Any]:
        self.ensure_container()
        self._stop_ros_processes()
        self.last_mode = "idle"
        self.last_message = "Stopped SLAM/navigation ROS2 processes"
        self.last_updated = time.time()
        return {"ok": True, "mode": self.last_mode}

    def send_initial_pose(self, x: float, y: float, theta: float) -> dict[str, Any]:
        message = self._initial_pose_message(x, y, theta)
        result = self._publish_once("/initialpose", "geometry_msgs/msg/PoseWithCovarianceStamped", message)
        self.last_message = f"Initial pose published: x={x:.2f}, y={y:.2f}, theta={theta:.2f}"
        self.last_updated = time.time()
        return {"ok": result.ok, "topic": "/initialpose", "pose": {"x": x, "y": y, "theta": theta}, "stdout": result.stdout[-1200:]}

    def send_goal_pose(self, x: float, y: float, theta: float) -> dict[str, Any]:
        message = self._pose_stamped_message(x, y, theta)
        result = self._publish_once("/goal_pose", "geometry_msgs/msg/PoseStamped", message)
        self.last_mode = "navigation_goal"
        self.last_message = f"Goal pose published: x={x:.2f}, y={y:.2f}, theta={theta:.2f}"
        self.last_updated = time.time()
        return {"ok": result.ok, "topic": "/goal_pose", "pose": {"x": x, "y": y, "theta": theta}, "stdout": result.stdout[-1200:]}

    def list_maps(self, refresh_meta: bool = True) -> list[dict[str, Any]]:
        command = f"find {shlex.quote(self.remote_maps_dir)} -maxdepth 1 -type f -name '*.yaml' -printf '%f|%s|%TY-%Tm-%Td %TH:%TM\\n' 2>/dev/null || true"
        result = self._ssh(command, timeout_sec=6)
        maps: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            parts = line.strip().split("|")
            if len(parts) < 3:
                continue
            name = self._sanitize_map_file(parts[0])
            item: dict[str, Any] = {
                "name": name,
                "size": int(parts[1]) if parts[1].isdigit() else 0,
                "modified": parts[2],
                "image_url": f"/api/slam/maps/{name}/image",
            }
            if refresh_meta:
                try:
                    item["meta"] = self.fetch_map(name)["meta"]
                except Exception as exc:
                    item["error"] = str(exc)
            maps.append(item)
        return maps

    def fetch_map(self, map_name: str) -> dict[str, Any]:
        safe_map = self._sanitize_map_file(map_name)
        yaml_path = f"{self.remote_maps_dir}/{safe_map}"
        yaml_text = self._ssh(f"cat {shlex.quote(yaml_path)}", timeout_sec=5).stdout
        meta = self._parse_map_yaml(yaml_text)
        image_path = self._map_image_host_path(meta.get("image", ""), yaml_path)
        image_b64 = self._ssh(f"base64 -w0 {shlex.quote(image_path)}", timeout_sec=8).stdout.strip()
        pgm = base64.b64decode(image_b64)
        png, width, height = self._pgm_to_png(pgm)

        meta.update({
            "name": safe_map,
            "width": width,
            "height": height,
            "resolution": float(meta.get("resolution", 0.05)),
            "origin": meta.get("origin", [-10.0, -10.0, 0.0]),
        })
        png_path = self.cache_dir / f"{safe_map}.png"
        json_path = self.cache_dir / f"{safe_map}.json"
        png_path.write_bytes(png)
        json_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "ok": True,
            "name": safe_map,
            "meta": meta,
            "image_path": png_path,
            "image_url": f"/api/slam/maps/{safe_map}/image",
        }

    def map_image_path(self, map_name: str) -> Path:
        safe_map = self._sanitize_map_file(map_name)
        png_path = self.cache_dir / f"{safe_map}.png"
        if not png_path.exists():
            self.fetch_map(safe_map)
        return png_path

    def logs(self) -> dict[str, Any]:
        if not self._container_running():
            return {"ok": True, "logs": "icar_web_nav container is not running yet."}
        files = [
            "/tmp/icar_slam_mapping_gmapping.log",
            "/tmp/icar_slam_mapping_cartographer.log",
            "/tmp/icar_slam_mapping_rtabmap.log",
            "/tmp/icar_slam_laser_bringup.log",
            "/tmp/icar_slam_navigation_dwa.log",
            "/tmp/icar_slam_navigation_teb.log",
            "/tmp/icar_slam_navigation_rtabmap.log",
        ]
        quoted = " ".join(shlex.quote(file) for file in files)
        result = self._docker_exec(f"tail -n 80 {quoted} 2>/dev/null || true", timeout_sec=5, tolerate=True)
        return {"ok": True, "logs": result.stdout}

    def ensure_container(self) -> dict[str, Any]:
        if self._container_running():
            return {"ok": True, "stdout": f"{self.container_name} already running"}
        script = f"""
set -e
name={shlex.quote(self.container_name)}
image={shlex.quote(self.image_name)}
mkdir -p /home/jetson/maps
if docker ps --format '{{{{.Names}}}}' | grep -Fxq "$name"; then
  echo "$name already running"
  exit 0
fi
if docker ps -a --format '{{{{.Names}}}}' | grep -Fxq "$name"; then
  docker start "$name" >/dev/null
  echo "$name started"
  exit 0
fi
args="--name $name --network host -e DISPLAY=:0 -e ROBOT_TYPE={self.robot_type} -e RPLIDAR_TYPE={self.rplidar_type}"
for dev in /dev/myserial /dev/rplidar /dev/input /dev/video0 /dev/astradepth /dev/astrauvc; do
  if [ -e "$dev" ]; then args="$args --device=$dev:$dev"; fi
done
for bind in /tmp/.X11-unix:/tmp/.X11-unix /home/jetson/code/yahboomcar_ws:/root/yahboomcar_ros2_ws/yahboomcar_ws /home/jetson/code/software/library_ws:/root/yahboomcar_ros2_ws/software/library_ws /home/jetson/maps:/root/maps; do
  host_path="${{bind%%:*}}"
  if [ -e "$host_path" ]; then args="$args -v $bind"; fi
done
docker run -dit $args "$image" bash -lc 'sleep infinity' >/dev/null
echo "$name created"
"""
        result = self._ssh(script, timeout_sec=20)
        return {"ok": True, "stdout": result.stdout.strip()}

    def _container_running(self) -> bool:
        try:
            output = self._ssh(
                f"docker inspect -f '{{{{.State.Running}}}}' {shlex.quote(self.container_name)} 2>/dev/null || true",
                timeout_sec=4,
                tolerate=True,
            ).stdout.strip()
            return output == "true"
        except Exception:
            return False

    def _stop_ros_processes(self) -> None:
        patterns = [
            "map_gmapping",
            "map_cartographer",
            "map_rtabmap",
            "laser_bringup",
            "navigation_dwa",
            "navigation_teb",
            "navigation_rtabmap",
            "save_map_launch",
            "nav2_",
            "amcl",
            "map_server",
            "planner_server",
            "controller_server",
            "bt_navigator",
            "slam_gmapping",
            "cartographer",
            "sllidar",
            "yahboomcar_bringup",
        ]
        joined = "|".join(re.escape(pattern) for pattern in patterns)
        self._docker_exec(f"pkill -f '{joined}' || true", timeout_sec=6, tolerate=True)
        time.sleep(1)

    def _publish_once(self, topic: str, msg_type: str, message: str) -> CommandResult:
        self.ensure_container()
        command = f"timeout 10s ros2 topic pub --once {shlex.quote(topic)} {shlex.quote(msg_type)} {shlex.quote(message)}"
        return self._docker_exec(f"{self._ros_setup()} && {command}", timeout_sec=14)

    def _docker_exec_detached(self, log_file: str, command: str) -> CommandResult:
        full_command = f"{self._ros_setup()} && {command} > {shlex.quote(log_file)} 2>&1"
        remote = f"docker exec -d {shlex.quote(self.container_name)} bash -lc {shlex.quote(full_command)}"
        return self._ssh(remote, timeout_sec=6)

    def _docker_exec(self, command: str, timeout_sec: float, tolerate: bool = False) -> CommandResult:
        remote = f"docker exec {shlex.quote(self.container_name)} bash -lc {shlex.quote(command)}"
        return self._ssh(remote, timeout_sec=timeout_sec, tolerate=tolerate)

    def _ssh(self, script: str, timeout_sec: float, tolerate: bool = False) -> CommandResult:
        executable = Path(r"C:\Program Files\PuTTY\plink.exe")
        if executable.exists():
            args = [
                str(executable),
                "-batch",
                "-hostkey",
                self.host_key,
                "-pw",
                self.password,
                self.target,
                f"bash -lc {shlex.quote(script)}",
            ]
        else:
            args = [
                "ssh",
                "-o",
                "ConnectTimeout=8",
                "-o",
                "ServerAliveInterval=15",
                "-o",
                "StrictHostKeyChecking=accept-new",
                self.target,
                f"bash -lc {shlex.quote(script)}",
            ]
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
        result = CommandResult(
            ok=completed.returncode == 0,
            command=" ".join(args[:-1] + ["<remote-script>"]),
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
        )
        if not result.ok and not tolerate:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"remote command failed: {result.returncode}")
        return result

    def _ros_setup(self) -> str:
        return (
            f"export ROBOT_TYPE={self.robot_type}; "
            f"export RPLIDAR_TYPE={self.rplidar_type}; "
            "source /opt/ros/foxy/setup.bash && "
            "source /root/yahboomcar_ros2_ws/yahboomcar_ws/install/setup.bash && "
            "source /root/yahboomcar_ros2_ws/software/library_ws/install/setup.bash"
        )

    def _pose_stamped_message(self, x: float, y: float, theta: float) -> str:
        z, w = self._yaw_to_quaternion(theta)
        return (
            "{header: {frame_id: 'map'}, pose: {position: "
            + f"{{x: {x:.4f}, y: {y:.4f}, z: 0.0}}"
            + ", orientation: "
            + f"{{x: 0.0, y: 0.0, z: {z:.8f}, w: {w:.8f}}}"
            + "}}"
        )

    def _initial_pose_message(self, x: float, y: float, theta: float) -> str:
        z, w = self._yaw_to_quaternion(theta)
        covariance = [0.0] * 36
        covariance[0] = 0.25
        covariance[7] = 0.25
        covariance[35] = 0.06853891945200942
        covariance_text = ", ".join(f"{value:.8f}" for value in covariance)
        return (
            "{header: {frame_id: 'map'}, pose: {pose: {position: "
            + f"{{x: {x:.4f}, y: {y:.4f}, z: 0.0}}"
            + ", orientation: "
            + f"{{x: 0.0, y: 0.0, z: {z:.8f}, w: {w:.8f}}}"
            + "}, covariance: ["
            + covariance_text
            + "]}}"
        )

    def _yaw_to_quaternion(self, theta: float) -> tuple[float, float]:
        return math.sin(theta / 2.0), math.cos(theta / 2.0)

    def _sanitize_map_stem(self, value: str) -> str:
        stem = value.strip()
        if stem.endswith(".yaml"):
            stem = stem[:-5]
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem)
        stem = stem.strip("._-") or "yahboomcar_web"
        return stem[:80]

    def _sanitize_map_file(self, value: str) -> str:
        stem = self._sanitize_map_stem(value)
        return f"{stem}.yaml"

    def _parse_map_yaml(self, text: str) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            value = value.strip()
            if key == "origin":
                meta[key] = [float(part.strip()) for part in value.strip("[]").split(",") if part.strip()]
            elif key in {"resolution", "occupied_thresh", "free_thresh"}:
                meta[key] = float(value)
            elif key in {"negate"}:
                meta[key] = int(value)
            else:
                meta[key] = value
        return meta

    def _map_image_host_path(self, image_value: str, yaml_path: str) -> str:
        if image_value.startswith("/root/yahboomcar_ros2_ws/yahboomcar_ws/"):
            return image_value.replace("/root/yahboomcar_ros2_ws/yahboomcar_ws/", "/home/jetson/code/yahboomcar_ws/", 1)
        if image_value.startswith("/"):
            return image_value
        return str(Path(yaml_path).parent / image_value)

    def _pgm_to_png(self, data: bytes) -> tuple[bytes, int, int]:
        offset = 0

        def token() -> bytes:
            nonlocal offset
            while offset < len(data) and data[offset] in b" \t\r\n":
                offset += 1
            if offset < len(data) and data[offset] == ord("#"):
                while offset < len(data) and data[offset] not in b"\r\n":
                    offset += 1
                return token()
            start = offset
            while offset < len(data) and data[offset] not in b" \t\r\n":
                offset += 1
            return data[start:offset]

        magic = token()
        if magic not in {b"P5", b"P2"}:
            raise ValueError("Unsupported map image format; expected PGM P5/P2")
        width = int(token())
        height = int(token())
        max_value = int(token())
        while offset < len(data) and data[offset] in b" \t\r\n":
            offset += 1

        if magic == b"P5":
            pixels = data[offset:offset + width * height]
        else:
            values = [int(token()) for _ in range(width * height)]
            pixels = bytes(values)
        if len(pixels) < width * height:
            raise ValueError("Truncated PGM map image")
        if max_value != 255:
            pixels = bytes(min(255, round(value * 255 / max_value)) for value in pixels)

        raw_rows = b"".join(b"\x00" + pixels[row * width:(row + 1) * width] for row in range(height))
        return self._png_bytes(width, height, raw_rows), width, height

    def _png_bytes(self, width: int, height: int, raw_rows: bytes) -> bytes:
        def chunk(kind: bytes, payload: bytes) -> bytes:
            checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
            return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

        header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw_rows)) + chunk(b"IEND", b"")
