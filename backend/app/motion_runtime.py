from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import AppConfig, DATA_DIR, PROJECT_ROOT


@dataclass
class CommandResult:
    ok: bool
    command: str = ""
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


@dataclass
class LeaseInfo:
    owner: str = ""
    mode: str = ""
    started_at: float = 0.0
    manual_restore: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "mode": self.mode,
            "started_at": self.started_at,
            "manual_restore": self.manual_restore,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LeaseInfo:
        return cls(
            owner=str(data.get("owner", "")),
            mode=str(data.get("mode", "")),
            started_at=float(data.get("started_at", 0)),
            manual_restore=str(data.get("manual_restore", "none")),
        )


@dataclass
class ProcessInfo:
    pid: int
    cmdline: str


@dataclass
class MotionStatus:
    ok: bool
    host: str
    lease: LeaseInfo | None = None
    flock_held: bool = False
    container_running: bool = False
    supervisor_alive: bool = False
    nodes: dict[str, bool] = field(default_factory=lambda: {
        "Mcnamu_driver_X3": False,
        "sllidar_node": False,
        "laser_Avoidance_a1_X3": False,
        "laser_Tracker_a1_X3": False,
    })
    scan_active: bool = False
    scan_message_received: bool = False
    cmd_vel_publisher: str = ""
    manual_ready: bool = False
    manual_port_ready: bool = False
    bridge_ready: bool = False
    port_6001_ready: bool = False
    camera_8080_ready: bool = False
    serial_owner: str = ""
    errors: list[str] = field(default_factory=list)
    mode: str = "idle"
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "host": self.host,
            "lease": self.lease.to_dict() if self.lease else None,
            "flock_held": self.flock_held,
            "container_running": self.container_running,
            "supervisor_alive": self.supervisor_alive,
            "nodes": self.nodes,
            "scan_active": self.scan_active,
            "scan_message_received": self.scan_message_received,
            "cmd_vel_publisher": self.cmd_vel_publisher,
            "manual_ready": self.manual_ready,
            "manual_port_ready": self.manual_port_ready,
            "bridge_ready": self.bridge_ready,
            "port_6001_ready": self.port_6001_ready,
            "camera_8080_ready": self.camera_8080_ready,
            "serial_owner": self.serial_owner,
            "errors": self.errors,
            "mode": self.mode,
            "message": self.message,
        }


class MotionRuntimeManager:

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.motion = config.motion
        self.user = "jetson"
        self.password = "yahboom"
        self.host_key = "ssh-ed25519 255 SHA256:AJffjk3YWwStux7ZbdKdft3teC8b7Jsubuvv4zMYuD8"
        self.cache_dir = DATA_DIR / "motion"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def host(self) -> str:
        return self.config.car.host

    @property
    def target(self) -> str:
        return f"{self.user}@{self.host}"

    # ── SSH helpers ──────────────────────────────────────────────

    def _ssh(self, script: str, timeout_sec: float = 0, tolerate: bool = False) -> CommandResult:
        if timeout_sec <= 0:
            timeout_sec = self.motion.ssh_timeout_sec
        executable = Path(r"C:\Program Files\PuTTY\plink.exe")
        if executable.exists():
            args = [
                str(executable), "-batch", "-hostkey", self.host_key,
                "-pw", self.password, self.target,
                f"bash -lc {shlex.quote(script)}",
            ]
        else:
            args = [
                "ssh", "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=15",
                "-o", "StrictHostKeyChecking=accept-new", self.target,
                f"bash -lc {shlex.quote(script)}",
            ]
        try:
            completed = subprocess.run(
                args, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            msg = stderr or stdout or f"remote command timed out after {timeout_sec:.1f}s"
            result = CommandResult(ok=False, stdout=stdout, stderr=msg, returncode=-1)
            if tolerate:
                return result
            raise RuntimeError(msg) from exc
        result = CommandResult(
            ok=completed.returncode == 0,
            stdout=completed.stdout, stderr=completed.stderr,
            returncode=completed.returncode,
        )
        if not result.ok and not tolerate:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip()
                               or f"remote command failed: {result.returncode}")
        return result

    def _last_json_line(self, text: str) -> dict[str, Any]:
        for line in reversed((text or "").splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                continue
        return {}

    # ── Lease file management (remote) ───────────────────────────

    def _read_lease(self) -> LeaseInfo | None:
        result = self._ssh(
            f"cat {shlex.quote(self.motion.lease_file)} 2>/dev/null || true",
            timeout_sec=5, tolerate=True,
        )
        data = self._last_json_line(result.stdout)
        return LeaseInfo.from_dict(data) if data else None

    def _lease_exists(self) -> bool:
        result = self._ssh(
            f"test -f {shlex.quote(self.motion.lease_file)} && echo true || echo false",
            timeout_sec=5, tolerate=True,
        )
        return result.stdout.strip() == "true"

    def _delete_lease(self) -> None:
        self._ssh(f"rm -f {shlex.quote(self.motion.lease_file)}", timeout_sec=5, tolerate=True)

    def _delete_pid_file(self) -> None:
        self._ssh(f"rm -f {shlex.quote(self.motion.supervisor_pid_file)}", timeout_sec=5, tolerate=True)

    # ── Flock management ─────────────────────────────────────────

    def _flock_held(self) -> bool:
        result = self._ssh(
            f"fuser {shlex.quote(self.motion.lock_file)} 2>/dev/null || true",
            timeout_sec=5, tolerate=True,
        )
        return bool(result.stdout.strip())

    # ── Process identification ───────────────────────────────────

    def _list_python_processes(self) -> list[ProcessInfo]:
        script = r"""
for pid in $(pgrep -x python3); do
  cmd=$(cat /proc/$pid/cmdline 2>/dev/null | tr '\0' ' ')
  if [ -n "$cmd" ]; then
    echo "$pid $cmd"
  fi
done
"""
        result = self._ssh(script, timeout_sec=6, tolerate=True)
        processes: list[ProcessInfo] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                try:
                    processes.append(ProcessInfo(pid=int(parts[0]), cmdline=parts[1]))
                except ValueError:
                    continue
        return processes

    def _find_process(self, glob_pattern: str) -> ProcessInfo | None:
        for proc in self._list_python_processes():
            if self._cmdline_matches(proc.cmdline, glob_pattern):
                return proc
        return None

    def _cmdline_matches(self, cmdline: str, glob_pattern: str) -> bool:
        import fnmatch
        return fnmatch.fnmatch(cmdline, glob_pattern)

    def _serial_owner_pids(self) -> list[int]:
        result = self._ssh(
            "fuser /dev/myserial 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+$' || true",
            timeout_sec=5, tolerate=True,
        )
        pids: list[int] = []
        for line in result.stdout.splitlines():
            try:
                pids.append(int(line.strip()))
            except ValueError:
                continue
        return pids

    def _identify_manual_restore(self) -> str:
        app = self._find_process(self.motion.app_path_glob)
        bridge = self._find_process(self.motion.bridge_path_glob)
        app_owns = app is not None and app.pid in self._serial_owner_pids()
        bridge_owns = bridge is not None and bridge.pid in self._serial_owner_pids()
        if app_owns:
            return "builtin_app"
        if bridge_owns:
            return "manual_bridge"
        return "none"

    def _unknown_serial_owners(self, known_pids: set[int]) -> list[ProcessInfo]:
        unknown: list[ProcessInfo] = []
        for pid in self._serial_owner_pids():
            if pid in known_pids:
                continue
            cmdline = self._proc_cmdline(pid)
            unknown.append(ProcessInfo(pid=pid, cmdline=cmdline))
        return unknown

    def _proc_cmdline(self, pid: int) -> str:
        result = self._ssh(
            f"cat /proc/{pid}/cmdline 2>/dev/null | tr '\\0' ' ' || true",
            timeout_sec=5, tolerate=True,
        )
        return result.stdout.strip()

    def _pid_alive(self, pid: int) -> bool:
        result = self._ssh(f"kill -0 {pid} 2>/dev/null && echo alive || echo dead", timeout_sec=5, tolerate=True)
        return result.stdout.strip() == "alive"

    def _pid_cmdline_matches(self, pid: int, pattern: str) -> bool:
        cmdline = self._proc_cmdline(pid)
        return self._cmdline_matches(cmdline, pattern)

    # ── Container management ─────────────────────────────────────

    def _container_running(self) -> bool:
        result = self._ssh(
            f"docker inspect -f '{{{{.State.Running}}}}' {shlex.quote(self.motion.container_name)} 2>/dev/null || echo false",
            timeout_sec=5, tolerate=True,
        )
        return "true" in result.stdout.strip().splitlines()

    def _ensure_container(self) -> CommandResult:
        if self._container_running():
            return CommandResult(ok=True, stdout=f"{self.motion.container_name} already running")
        script = f"""
set -e
name={shlex.quote(self.motion.container_name)}
image={shlex.quote(self.motion.image_name)}
if docker ps --format '{{{{.Names}}}}' | grep -Fxq "$name"; then
  echo "$name already running"
  exit 0
fi
if docker ps -a --format '{{{{.Names}}}}' | grep -Fxq "$name"; then
  docker start "$name" >/dev/null
  echo "$name started"
  exit 0
fi
args="--name $name --network host -e DISPLAY=:0 -e ROBOT_TYPE={self.motion.robot_type} -e RPLIDAR_TYPE={self.motion.rplidar_type}"
for dev in /dev/myserial /dev/rplidar; do
  if [ -e "$dev" ]; then args="$args --device=$dev:$dev"; fi
done
bind_src="{self.motion.host_icar_ws}"
bind_dst="{self.motion.container_icar_ws}"
if [ -e "$bind_src" ]; then args="$args -v $bind_src:$bind_dst"; fi
lib_src="{self.motion.host_library_ws}"
lib_dst="{self.motion.container_library_ws}"
if [ -e "$lib_src" ]; then args="$args -v $lib_src:$lib_dst"; fi
docker run -dit $args "$image" bash -lc 'sleep infinity' >/dev/null
echo "$name created"
"""
        result = self._ssh(script, timeout_sec=25, tolerate=True)
        output = "\n".join(p for p in (result.stdout.strip(), result.stderr.strip()) if p)
        accepted = (
            result.ok or f"{self.motion.container_name} already running" in output
            or f"{self.motion.container_name} started" in output
            or f"{self.motion.container_name} created" in output
        )
        if not accepted:
            raise RuntimeError(output or f"failed to ensure {self.motion.container_name}: {result.returncode}")
        return CommandResult(ok=True, stdout=output)

    def _stop_container(self) -> CommandResult:
        name = shlex.quote(self.motion.container_name)
        result = self._ssh(f"docker stop {name} 2>/dev/null || true", timeout_sec=20, tolerate=True)
        return CommandResult(ok=True, stdout=result.stdout.strip(), stderr=result.stderr.strip())

    def _docker_exec(self, command: str, timeout_sec: float = 0, tolerate: bool = False) -> CommandResult:
        if timeout_sec <= 0:
            timeout_sec = self.motion.ssh_timeout_sec
        remote = f"docker exec {shlex.quote(self.motion.container_name)} bash -lc {shlex.quote(command)}"
        return self._ssh(remote, timeout_sec=timeout_sec, tolerate=tolerate)

    def _ros_setup(self) -> str:
        m = self.motion
        return (
            f"export ROBOT_TYPE={m.robot_type}; "
            f"export RPLIDAR_TYPE={m.rplidar_type}; "
            "source /opt/ros/foxy/setup.bash 2>/dev/null; "
            f"source {m.container_icar_ws}/install/setup.bash 2>/dev/null; "
            f"source {m.container_library_ws}/install/setup.bash 2>/dev/null; "
            "true"
        )

    # ── Stop app / bridge ────────────────────────────────────────

    def _stop_process_by_pattern(self, glob_pattern: str, timeout_sec: float = 8) -> dict[str, Any]:
        proc = self._find_process(glob_pattern)
        if proc is None:
            return {"ok": True, "message": f"no process matching {glob_pattern} found"}
        self._ssh(f"kill -KILL {proc.pid} 2>/dev/null || true", timeout_sec=5, tolerate=True)
        deadline = time.time() + timeout_sec
        stopped = False
        while time.time() < deadline:
            if not self._pid_alive(proc.pid):
                stopped = True
                break
            time.sleep(0.3)
        if not stopped:
            self._ssh(f"kill -KILL {proc.pid} 2>/dev/null || true", timeout_sec=3, tolerate=True)
            time.sleep(0.5)
        alive = self._pid_alive(proc.pid)
        # Also check if a NEW process with the same pattern started
        new_proc = self._find_process(glob_pattern)
        restarted = new_proc is not None and new_proc.pid != proc.pid
        return {
            "ok": not alive,
            "message": f"PID {proc.pid} {'killed' if not alive else 'still alive'}",
            "pid": proc.pid,
            "cmdline": proc.cmdline,
            "restarted": restarted,
            "new_pid": new_proc.pid if restarted else None,
        }

    def _stop_manual_services(self) -> dict[str, Any]:
        results: dict[str, Any] = {}
        results["app"] = self._stop_process_by_pattern(self.motion.app_path_glob)
        results["bridge"] = self._stop_process_by_pattern(self.motion.bridge_path_glob)

        # Wait for serial to free, with escalating force
        deadline = time.time() + 8
        while time.time() < deadline:
            pids = self._serial_owner_pids()
            if not pids:
                break
            time.sleep(0.5)

        results["serial_pids_after"] = self._serial_owner_pids()

        # If known processes still hold the serial, force-release with fuser -k
        if results["serial_pids_after"]:
            self._ssh("fuser -k /dev/myserial 2>/dev/null || true", timeout_sec=5, tolerate=True)
            time.sleep(2)
            results["serial_pids_after"] = self._serial_owner_pids()
            results["fuser_k_used"] = True

        results["serial_free"] = len(self._serial_owner_pids()) == 0
        results["ok"] = results["app"]["ok"] and results["bridge"]["ok"] and results["serial_free"]
        return results

    def _unknown_serial_check(self, known_pids: set[int]) -> list[dict[str, Any]]:
        unknown = self._unknown_serial_owners(known_pids)
        return [{"pid": p.pid, "cmdline": p.cmdline} for p in unknown]

    # ── Restore manual control ───────────────────────────────────

    def _restore_manual(self, restore_mode: str) -> dict[str, Any]:
        if restore_mode == "builtin_app":
            return self._restore_builtin_app()
        if restore_mode == "manual_bridge":
            return self._restore_bridge()
        return {"ok": True, "manual_ready": False, "manual_port_ready": False, "message": "manual_restore=none, no service restored"}

    def _restore_builtin_app(self) -> dict[str, Any]:
        proc = self._find_process(self.motion.app_path_glob)
        if proc is None:
            script = (
                f"cd /home/jetson/Rosmaster-App/rosmaster && "
                f"nohup python3 app.py >/tmp/icar_app.log 2>&1 &"
            )
            self._ssh(script, timeout_sec=8, tolerate=True)
        deadline = time.time() + 25
        app_proc = None
        while time.time() < deadline:
            app_proc = self._find_process(self.motion.app_path_glob)
            if app_proc and app_proc.pid in self._serial_owner_pids():
                break
            time.sleep(0.7)
        manual_ready = app_proc is not None and app_proc.pid in self._serial_owner_pids()
        port_6000_open = self._port_open(6000)
        return {
            "ok": manual_ready,
            "manual_ready": manual_ready,
            "manual_port_ready": port_6000_open,
            "pid": app_proc.pid if app_proc else None,
            "message": "app.py restored" if manual_ready else "app.py restore incomplete",
        }

    def _restore_bridge(self) -> dict[str, Any]:
        proc = self._find_process(self.motion.bridge_path_glob)
        if proc is None:
            script = (
                f"cd /home/jetson/Rosmaster-App/rosmaster && "
                f"nohup python3 icar_rosmaster_tcp_bridge.py --host 0.0.0.0 --port 6001 --speed 50 --pulse-timeout-sec 0.45 "
                f">/tmp/icar_bridge.log 2>&1 &"
            )
            self._ssh(script, timeout_sec=8, tolerate=True)
        deadline = time.time() + 12
        bridge_proc = None
        while time.time() < deadline:
            bridge_proc = self._find_process(self.motion.bridge_path_glob)
            if bridge_proc and bridge_proc.pid in self._serial_owner_pids():
                break
            time.sleep(0.6)
        manual_ready = bridge_proc is not None and bridge_proc.pid in self._serial_owner_pids()
        port_6001_open = self._port_open(6001)
        return {
            "ok": manual_ready and port_6001_open,
            "manual_ready": manual_ready,
            "manual_port_ready": port_6001_open,
            "pid": bridge_proc.pid if bridge_proc else None,
            "message": "bridge restored" if manual_ready and port_6001_open else "bridge restore incomplete",
        }

    def _port_open(self, port: int, timeout_sec: float = 1.5) -> bool:
        import socket
        try:
            with socket.create_connection((self.host, port), timeout=timeout_sec):
                return True
        except OSError:
            return False

    # ── ROS node management inside container ─────────────────────

    def _start_driver_node(self) -> CommandResult:
        m = self.motion
        command = (
            f"{self._ros_setup()} && "
            f"nohup ros2 run {m.driver_package} {m.driver_node} "
            f">/tmp/icar_mcnamu_driver.log 2>&1 &"
        )
        return self._docker_exec(command, timeout_sec=10, tolerate=True)

    def _start_lidar_node(self) -> CommandResult:
        m = self.motion
        command = (
            f"{self._ros_setup()} && "
            f"nohup ros2 launch {m.lidar_launch_package} {m.lidar_launch_file} "
            f">/tmp/icar_sllidar.log 2>&1 &"
        )
        return self._docker_exec(command, timeout_sec=10, tolerate=True)

    def _start_avoidance_node(self, linear: float = 0, angular: float = 0) -> CommandResult:
        m = self.motion
        lin = linear if linear > 0 else m.default_linear
        ang = angular if angular > 0 else m.default_angular
        command = (
            f"{self._ros_setup()} && "
            f"nohup ros2 run {m.avoidance_package} {m.avoidance_node} "
            f"--ros-args -p linear:={lin} -p angular:={ang} -p Switch:=false "
            f">/tmp/icar_laser_avoidance.log 2>&1 &"
        )
        return self._docker_exec(command, timeout_sec=10, tolerate=True)

    def _node_running(self, node_name: str) -> bool:
        result = self._docker_exec(
            f"pgrep -f {shlex.quote(node_name)} || true",
            timeout_sec=6, tolerate=True,
        )
        return bool(result.stdout.strip())

    def _start_tracking_node(self) -> CommandResult:
        m = self.motion
        command = (
            f"{self._ros_setup()} && "
            f"nohup ros2 run {m.tracking_package} {m.tracking_node} "
            f">/tmp/icar_laser_tracking.log 2>&1 &"
        )
        return self._docker_exec(command, timeout_sec=10, tolerate=True)

    def _stop_avoidance_node(self) -> None:
        m = self.motion
        self._docker_exec(
            f"pkill -TERM -f {shlex.quote(m.avoidance_node)} 2>/dev/null || true",
            timeout_sec=6, tolerate=True,
        )
        time.sleep(0.5)

    def _stop_tracking_node(self) -> None:
        self._docker_exec(
            f"pkill -TERM -f {shlex.quote(self.motion.tracking_node)} 2>/dev/null || true",
            timeout_sec=6, tolerate=True,
        )
        time.sleep(0.5)

    def _publish_zero_velocity(self) -> CommandResult:
        return self._docker_exec(
            f"{self._ros_setup()} && "
            f"timeout {self.motion.zero_vel_dwell_sec}s ros2 topic pub -r 10 "
            f"/cmd_vel geometry_msgs/msg/Twist "
            f"'{{linear: {{x: 0.0}}, angular: {{z: 0.0}}}}'",
            timeout_sec=self.motion.zero_vel_dwell_sec + 4, tolerate=True,
        )

    def _stop_all_ros_nodes(self) -> None:
        patterns = [
            self.motion.driver_node,
            self.motion.avoidance_node,
            self.motion.tracking_node,
            "sllidar_node",
            "static_transform_publisher",
        ]
        for pattern in patterns:
            self._docker_exec(
                f"pkill -TERM -f {shlex.quote(pattern)} 2>/dev/null || true",
                timeout_sec=5, tolerate=True,
            )
        time.sleep(2)

    def _pub_cmd_vel_publisher(self) -> str:
        """Check which node publishes /cmd_vel by querying each candidate node."""
        for node_base in ("laser_Avoidance_a1", "laser_Tracker_a1"):
            result = self._docker_exec(
                f"{self._ros_setup()} && timeout 5s ros2 node info /{node_base} 2>/dev/null || true",
                timeout_sec=10, tolerate=True,
            )
            if "/cmd_vel" in result.stdout:
                return node_base
        # Fallback: raw topic info
        result = self._docker_exec(
            f"{self._ros_setup()} && timeout 5s ros2 topic info /cmd_vel 2>/dev/null || true",
            timeout_sec=10, tolerate=True,
        )
        if "Publisher count: 1" in result.stdout:
            return "has_publisher_unknown"
        if "Publisher count: 0" in result.stdout:
            return "none"
        return result.stdout.strip()[-200:]

    def _resolve_cmd_vel_publisher(self) -> str:
        return self._pub_cmd_vel_publisher()

    # ── Health check ──────────────────────────────────────────────

    def _check_scan_message(self) -> bool:
        sample = "/tmp/icar_scan_sample.$$"
        script = (
            f"{self._ros_setup()} && "
            f"sample={sample}; "
            f"timeout 3s ros2 topic echo /scan sensor_msgs/msg/LaserScan >\"$sample\" 2>/dev/null || true; "
            f"test -s \"$sample\" && echo HAS_DATA || echo NO_DATA; "
            f"rm -f \"$sample\""
        )
        result = self._docker_exec(script, timeout_sec=8, tolerate=True)
        return "HAS_DATA" in result.stdout

    def health_check(self) -> MotionStatus:
        m = self.motion
        status = MotionStatus(ok=False, host=self.host)
        try:
            lease = self._read_lease()
            status.lease = lease
            status.flock_held = self._flock_held()
            status.container_running = self._container_running()
            status.mode = lease.mode if lease else "idle"
        except Exception as exc:
            status.errors.append(f"basic check failed: {exc}")
            return status

        if not status.container_running:
            status.message = "container not running"
            return status

        try:
            status.nodes["Mcnamu_driver_X3"] = self._node_running(m.driver_node)
            status.nodes["sllidar_node"] = self._node_running("sllidar_node")
            status.nodes["laser_Avoidance_a1_X3"] = self._node_running(m.avoidance_node)
            status.nodes["laser_Tracker_a1_X3"] = self._node_running(m.tracking_node)

            status.scan_active = self._scan_publisher_count() > 0
            status.scan_message_received = self._check_scan_message()
            status.cmd_vel_publisher = self._pub_cmd_vel_publisher()

            all_nodes_ok = all(status.nodes.values())
            avoidance_base = m.avoidance_node.replace("_X3", "")
            tracking_base = m.tracking_node.replace("_X3", "")
            cmd_vel_ok = (status.cmd_vel_publisher in (avoidance_base, tracking_base, "has_publisher_unknown")
                          and status.cmd_vel_publisher != "none")
            status.ok = (
                all_nodes_ok
                and status.scan_active and status.scan_message_received
                and cmd_vel_ok
            )
            if not status.ok:
                if not all_nodes_ok:
                    dead = [k for k, v in status.nodes.items() if not v]
                    status.errors.append(f"dead nodes: {dead}")
                if not status.scan_message_received:
                    status.errors.append("/scan has no actual LaserScan messages")
                if not cmd_vel_ok:
                    status.errors.append(f"no avoidance/tracking node found in /cmd_vel publisher info")
            status.message = "healthy" if status.ok else "; ".join(status.errors)
        except Exception as exc:
            status.errors.append(f"health check error: {exc}")

        return status

    def _scan_publisher_count(self) -> int:
        result = self._docker_exec(
            f"{self._ros_setup()} && timeout 5s ros2 topic info /scan 2>/dev/null || true",
            timeout_sec=10, tolerate=True,
        )
        for line in result.stdout.splitlines():
            if "Publisher count:" in line:
                try:
                    return int(line.split(":")[-1].strip())
                except ValueError:
                    return 0
        return 0

    def _quick_check(self) -> MotionStatus:
        return self.health_check()

    # ── Full status (includes manual restore state) ──────────────

    def status(self) -> MotionStatus:
        s = self.health_check()
        try:
            app_proc = self._find_process(self.motion.app_path_glob)
            bridge_proc = self._find_process(self.motion.bridge_path_glob)
            serial_pids = self._serial_owner_pids()
            s.manual_ready = app_proc is not None and (app_proc.pid in serial_pids)
            s.manual_port_ready = self._port_open(6000)
            s.bridge_ready = bridge_proc is not None and (bridge_proc.pid in serial_pids)
            s.port_6001_ready = self._port_open(6001)
            s.camera_8080_ready = self._port_open(8080)
            owners: list[str] = []
            if app_proc and app_proc.pid in serial_pids:
                owners.append("app.py")
            if bridge_proc and bridge_proc.pid in serial_pids:
                owners.append("bridge")
            s.serial_owner = ", ".join(owners) if owners else "none"
            if not s.serial_owner or s.serial_owner == "none":
                s.serial_owner = ",".join(str(p) for p in serial_pids) if serial_pids else "none"
        except Exception as exc:
            s.errors.append(f"manual check error: {exc}")
        return s

    # ── Start laser avoidance ────────────────────────────────────

    def _ssh_sanity_check(self) -> dict[str, Any]:
        """Quick check that SSH to the Jetson is working."""
        result = self._ssh("echo SSH_OK", timeout_sec=6, tolerate=True)
        ok = result.ok and "SSH_OK" in result.stdout
        return {"ok": ok, "stdout": result.stdout[:200], "stderr": result.stderr[:200],
                "message": "SSH to Jetson is working" if ok else
                "SSH to Jetson FAILED — check PuTTY (plink.exe) at C:\\Program Files\\PuTTY\\plink.exe "
                "or set up passwordless SSH keys"}

    def start_laser_avoidance(self, owner: str = "", linear: float = 0, angular: float = 0) -> dict[str, Any]:
        steps: list[dict[str, Any]] = []

        def _step(name: str, ok: bool, **kwargs: Any) -> dict[str, Any]:
            s = {"step": name, "ok": ok, **kwargs}
            steps.append(s)
            return s

        # 0. SSH sanity check
        ssh_check = self._ssh_sanity_check()
        if not ssh_check["ok"]:
            return {"ok": False, "reason": "ssh_failed", "message": ssh_check["message"],
                    "steps": [_step("ssh_check", False, message=ssh_check.get("message", ""), stdout=ssh_check.get("stdout", "")[:200])]}

        _step("ssh_check", True)

        # 1. Check existing lease
        existing = self._read_lease()
        if existing and existing.mode in ("laser_avoidance", "laser_tracking"):
            return {"ok": False, "reason": "conflict",
                    "message": f"mode {existing.mode} already holds lease",
                    "lease": existing.to_dict(), "steps": steps}
        _step("lease_check", True, existing_mode=existing.mode if existing else "none")

        # 2. Identify current manual restore baseline
        all_procs = self._list_python_processes()
        serial_pids_before = self._serial_owner_pids()
        manual_restore = self._identify_manual_restore()
        app_proc = self._find_process(self.motion.app_path_glob)
        bridge_proc = self._find_process(self.motion.bridge_path_glob)
        known_pids: set[int] = set()
        if app_proc:
            known_pids.add(app_proc.pid)
        if bridge_proc:
            known_pids.add(bridge_proc.pid)
        _step("identify_manual", True, manual_restore=manual_restore,
              app_pid=app_proc.pid if app_proc else None,
              bridge_pid=bridge_proc.pid if bridge_proc else None,
              serial_pids_before=serial_pids_before,
              all_python_processes=[f"{p.pid}:{p.cmdline[:80]}" for p in all_procs[:20]])

        # 3. Best-effort stop via existing manual control
        try:
            self._stop_via_tcp()
            _step("tcp_stop", True)
        except Exception as exc:
            _step("tcp_stop", False, error=str(exc))

        # 4. Stop manual services
        stop_result = self._stop_manual_services()
        _step("stop_manual", bool(stop_result.get("ok")),
              app_killed=stop_result.get("app", {}).get("ok"),
              bridge_killed=stop_result.get("bridge", {}).get("ok"),
              serial_free=stop_result.get("serial_free"),
              fuser_used=stop_result.get("fuser_k_used", False))
        if not stop_result.get("ok"):
            return {"ok": False, "reason": "manual_stop_failed", "details": stop_result, "steps": steps}

        # 5. Verify serial port free
        time.sleep(1)
        serial_pids = self._serial_owner_pids()
        unknown = [p for p in serial_pids if p not in known_pids]
        still_alive = [p for p in serial_pids if p in known_pids]
        _step("serial_check", len(serial_pids) == 0,
              serial_pids=serial_pids, known_pids=list(known_pids),
              still_alive=still_alive, unknown=unknown)
        # Fail if ANY process still holds serial — known or unknown
        if still_alive:
            details = [{"pid": p, "cmdline": self._proc_cmdline(p), "reason": "known process still alive"} for p in still_alive]
            return {"ok": False, "reason": "serial_still_occupied",
                    "message": f"known processes ({still_alive}) still hold /dev/myserial after kill",
                    "details": details, "steps": steps}
        if unknown:
            details = [{"pid": p, "cmdline": self._proc_cmdline(p)} for p in unknown]
            return {"ok": False, "reason": "unknown_serial_owner", "unknown_pids": details,
                    "message": "unknown processes hold /dev/myserial; refusing to proceed", "steps": steps}

        # 6. Start container
        try:
            self._ensure_container()
            _step("container_start", True, container=self.motion.container_name)
        except Exception as exc:
            _step("container_start", False, error=str(exc))
            return {"ok": False, "reason": "container_failed", "message": str(exc), "steps": steps}

        # 7. Start ROS2 nodes (kill any strays first)
        self._stop_all_ros_nodes()
        time.sleep(1)
        self._start_driver_node()
        _step("driver_started", True)
        time.sleep(1.5)

        self._start_lidar_node()
        _step("lidar_started", True)
        time.sleep(3)

        self._start_avoidance_node(linear=linear, angular=angular)
        _step("avoidance_started", True)
        time.sleep(2)

        # 8. Write lease
        lease = LeaseInfo(
            owner=owner or f"console-{uuid.uuid4().hex[:8]}",
            mode="laser_avoidance",
            started_at=time.time(),
            manual_restore=manual_restore,
        )
        self._atomic_write_lease(lease)
        _step("lease_written", True, lease=lease.to_dict())

        # 9. Health check
        health_start = time.time()
        deadline = health_start + 25
        last_status: MotionStatus | None = None
        health_rounds = 0
        while time.time() < deadline:
            time.sleep(2)
            health_rounds += 1
            s = self._quick_check()
            last_status = s
            _step(f"health_round_{health_rounds}", s.ok,
                  nodes=s.nodes, scan_ok=s.scan_message_received,
                  cmd_vel=s.cmd_vel_publisher[:80] if s.cmd_vel_publisher else "")
            if s.ok:
                return {"ok": True, "status": s.to_dict(), "steps": steps,
                        "message": "laser avoidance healthy"}
            if s.errors:
                time.sleep(1)

        return {
            "ok": False, "reason": "health_check_failed", "steps": steps,
            "status": last_status.to_dict() if last_status else None,
            "message": "nodes did not become healthy within timeout",
        }

    def _stop_via_tcp(self) -> None:
        import socket
        for port in (6000, 6001):
            try:
                with socket.create_connection((self.host, port), timeout=1.0) as sock:
                    sock.sendall(b"$01150002FCFD#")
                    sock.settimeout(0.5)
                    sock.recv(64)
            except OSError:
                pass

    def _atomic_write_lease(self, lease: LeaseInfo) -> None:
        payload = json.dumps(lease.to_dict(), ensure_ascii=False)
        tmp_path = f"{self.motion.lease_file}.tmp.{os.getpid()}"
        script = (
            f"cat > {shlex.quote(tmp_path)} << 'LEASE_EOF'\n{payload}\nLEASE_EOF\n"
            f"mv {shlex.quote(tmp_path)} {shlex.quote(self.motion.lease_file)}"
        )
        self._ssh(script, timeout_sec=5, tolerate=False)

    # ── Stop laser avoidance ─────────────────────────────────────

    def stop_laser_avoidance(self, emergency: bool = False) -> dict[str, Any]:
        lease = self._read_lease()
        restore_mode = lease.manual_restore if lease else "none"
        result: dict[str, Any] = {"ok": True, "emergency": emergency, "steps": []}

        # 1. Stop avoidance node first
        try:
            self._stop_avoidance_node()
            result["steps"].append("avoidance_node_stopped")
        except Exception as exc:
            result["steps"].append(f"avoidance_stop_error: {exc}")

        # 2. Publish zero velocity
        if self._container_running():
            try:
                self._publish_zero_velocity()
                result["steps"].append("zero_velocity_sent")
            except Exception as exc:
                result["steps"].append(f"zero_vel_error: {exc}")

        # 3. Stop all ROS nodes
        try:
            self._stop_all_ros_nodes()
            result["steps"].append("ros_nodes_stopped")
        except Exception as exc:
            result["steps"].append(f"ros_stop_error: {exc}")

        # 4. Stop container
        try:
            self._stop_container()
            result["steps"].append("container_stopped")
        except Exception as exc:
            result["steps"].append(f"container_error: {exc}")

        # 5. Restore manual control
        restore_result = self._restore_manual(restore_mode)
        result["restore"] = restore_result
        result["steps"].append(f"manual_restore={restore_mode}")

        # 6. Clean up lease and PID files
        self._delete_lease()
        self._delete_pid_file()
        result["steps"].append("lease_cleaned")

        # 7. Verify serial port restored
        time.sleep(1)
        serial_pids = self._serial_owner_pids()
        result["serial_owner"] = serial_pids
        result["manual_ready"] = restore_result.get("manual_ready", False)
        result["manual_port_ready"] = restore_result.get("manual_port_ready", False)

        return result

    # ── Start / Stop laser tracking ──────────────────────────────

    def start_laser_tracking(self, owner: str = "") -> dict[str, Any]:
        steps: list[dict[str, Any]] = []

        def _step(name: str, ok: bool, **kwargs: Any) -> dict[str, Any]:
            s = {"step": name, "ok": ok, **kwargs}
            steps.append(s)
            return s

        # 0. SSH sanity check
        ssh_check = self._ssh_sanity_check()
        if not ssh_check["ok"]:
            return {"ok": False, "reason": "ssh_failed", "message": ssh_check["message"],
                    "steps": [_step("ssh_check", False, message=ssh_check.get("message", ""), stdout=ssh_check.get("stdout", "")[:200])]}
        _step("ssh_check", True)

        # 1. Check existing lease
        existing = self._read_lease()
        if existing and existing.mode in ("laser_avoidance", "laser_tracking"):
            return {"ok": False, "reason": "conflict",
                    "message": f"mode {existing.mode} already holds lease",
                    "lease": existing.to_dict(), "steps": steps}
        _step("lease_check", True, existing_mode=existing.mode if existing else "none")

        # 2. Identify current manual restore baseline
        all_procs = self._list_python_processes()
        serial_pids_before = self._serial_owner_pids()
        manual_restore = self._identify_manual_restore()
        app_proc = self._find_process(self.motion.app_path_glob)
        bridge_proc = self._find_process(self.motion.bridge_path_glob)
        known_pids: set[int] = set()
        if app_proc:
            known_pids.add(app_proc.pid)
        if bridge_proc:
            known_pids.add(bridge_proc.pid)
        _step("identify_manual", True, manual_restore=manual_restore,
              app_pid=app_proc.pid if app_proc else None,
              bridge_pid=bridge_proc.pid if bridge_proc else None,
              serial_pids_before=serial_pids_before,
              all_python_processes=[f"{p.pid}:{p.cmdline[:80]}" for p in all_procs[:20]])

        # 3. Best-effort stop via TCP
        try:
            self._stop_via_tcp()
            _step("tcp_stop", True)
        except Exception as exc:
            _step("tcp_stop", False, error=str(exc))

        # 4. Stop manual services
        stop_result = self._stop_manual_services()
        _step("stop_manual", bool(stop_result.get("ok")),
              app_killed=stop_result.get("app", {}).get("ok"),
              bridge_killed=stop_result.get("bridge", {}).get("ok"),
              serial_free=stop_result.get("serial_free"),
              fuser_used=stop_result.get("fuser_k_used", False))
        if not stop_result.get("ok"):
            return {"ok": False, "reason": "manual_stop_failed", "details": stop_result, "steps": steps}

        # 5. Verify serial port free
        time.sleep(1)
        serial_pids = self._serial_owner_pids()
        unknown = [p for p in serial_pids if p not in known_pids]
        still_alive = [p for p in serial_pids if p in known_pids]
        _step("serial_check", len(serial_pids) == 0,
              serial_pids=serial_pids, known_pids=list(known_pids),
              still_alive=still_alive, unknown=unknown)
        if still_alive:
            details = [{"pid": p, "cmdline": self._proc_cmdline(p), "reason": "known process still alive"} for p in still_alive]
            return {"ok": False, "reason": "serial_still_occupied",
                    "message": f"known processes still hold /dev/myserial after kill",
                    "details": details, "steps": steps}
        if unknown:
            details = [{"pid": p, "cmdline": self._proc_cmdline(p)} for p in unknown]
            return {"ok": False, "reason": "unknown_serial_owner", "unknown_pids": details,
                    "message": "unknown processes hold /dev/myserial; refusing to proceed", "steps": steps}

        # 6. Start container
        try:
            self._ensure_container()
            _step("container_start", True, container=self.motion.container_name)
        except Exception as exc:
            _step("container_start", False, error=str(exc))
            return {"ok": False, "reason": "container_failed", "message": str(exc), "steps": steps}

        # 7. Start ROS2 nodes (kill any strays first)
        self._stop_all_ros_nodes()
        time.sleep(1)
        self._start_driver_node()
        _step("driver_started", True)
        time.sleep(1.5)

        self._start_lidar_node()
        _step("lidar_started", True)
        time.sleep(3)

        self._start_tracking_node()
        _step("tracking_started", True)
        time.sleep(2)

        # 8. Write lease
        lease = LeaseInfo(
            owner=owner or f"console-{uuid.uuid4().hex[:8]}",
            mode="laser_tracking",
            started_at=time.time(),
            manual_restore=manual_restore,
        )
        self._atomic_write_lease(lease)
        _step("lease_written", True, lease=lease.to_dict())

        # 9. Health check
        health_start = time.time()
        deadline = health_start + 25
        last_status: MotionStatus | None = None
        health_rounds = 0
        while time.time() < deadline:
            time.sleep(2)
            health_rounds += 1
            s = self._quick_check()
            last_status = s
            _step(f"health_round_{health_rounds}", s.ok,
                  nodes=s.nodes, scan_ok=s.scan_message_received,
                  cmd_vel=s.cmd_vel_publisher[:80] if s.cmd_vel_publisher else "")
            if s.ok:
                return {"ok": True, "status": s.to_dict(), "steps": steps,
                        "message": "laser tracking healthy"}
            if s.errors:
                time.sleep(1)

        return {
            "ok": False, "reason": "health_check_failed", "steps": steps,
            "status": last_status.to_dict() if last_status else None,
            "message": "tracking nodes did not become healthy within timeout",
        }

    def stop_laser_tracking(self, emergency: bool = False) -> dict[str, Any]:
        lease = self._read_lease()
        restore_mode = lease.manual_restore if lease else "none"
        result: dict[str, Any] = {"ok": True, "emergency": emergency, "steps": []}

        # 1. Stop tracking node first
        try:
            self._stop_tracking_node()
            result["steps"].append("tracking_node_stopped")
        except Exception as exc:
            result["steps"].append(f"tracking_stop_error: {exc}")

        # 2. Publish zero velocity
        if self._container_running():
            try:
                self._publish_zero_velocity()
                result["steps"].append("zero_velocity_sent")
            except Exception as exc:
                result["steps"].append(f"zero_vel_error: {exc}")

        # 3. Stop all ROS nodes
        try:
            self._stop_all_ros_nodes()
            result["steps"].append("ros_nodes_stopped")
        except Exception as exc:
            result["steps"].append(f"ros_stop_error: {exc}")

        # 4. Stop container
        try:
            self._stop_container()
            result["steps"].append("container_stopped")
        except Exception as exc:
            result["steps"].append(f"container_error: {exc}")

        # 5. Restore manual control
        restore_result = self._restore_manual(restore_mode)
        result["restore"] = restore_result
        result["steps"].append(f"manual_restore={restore_mode}")

        # 6. Clean up lease and PID files
        self._delete_lease()
        self._delete_pid_file()
        result["steps"].append("lease_cleaned")

        # 7. Verify serial port restored
        time.sleep(1)
        serial_pids = self._serial_owner_pids()
        result["serial_owner"] = serial_pids
        result["manual_ready"] = restore_result.get("manual_ready", False)
        result["manual_port_ready"] = restore_result.get("manual_port_ready", False)

        return result

    def emergency_stop(self, reason: str = "web") -> dict[str, Any]:
        lease = self._read_lease()
        if lease and lease.mode == "laser_tracking":
            return self.stop_laser_tracking(emergency=True)
        return self.stop_laser_avoidance(emergency=True)
