from __future__ import annotations

import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from .config import AppConfig, PROJECT_ROOT


class CarRuntimeRecovery:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.scripts_dir = PROJECT_ROOT / "scripts"

    def port_open(self, host: str, port: int, timeout_sec: float = 1.2) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout_sec):
                return True
        except OSError:
            return False

    def check_ports(self, host: str | None = None) -> dict[str, bool]:
        target = host or self.config.car.host
        return {
            "ssh_22": self.port_open(target, 22, 1.2),
            "control_6000": self.port_open(target, 6000, 1.2),
            "bridge_6001": self.port_open(target, 6001, 1.2),
            "camera_6500": self.port_open(target, 6500, 1.2),
            "camera_8080": self.port_open(target, 8080, 1.2),
        }

    def recover_builtin_app(self, host: str | None = None) -> dict[str, Any]:
        target = host or self.config.car.host
        before = self.check_ports(target)
        commands: list[dict[str, Any]] = []

        if before["control_6000"] and before["camera_6500"]:
            return {"ok": True, "host": target, "before": before, "after": before, "commands": commands}

        if not before["ssh_22"]:
            return {
                "ok": False,
                "host": target,
                "before": before,
                "after": before,
                "commands": commands,
                "error": "SSH 22 is closed; the car may still be booting or disconnected from the hotspot.",
            }

        builtin = self.run_script("start_car_builtin_app_ssh.ps1", target, timeout_sec=18, extra_args=["-Restart"])
        commands.append(builtin)
        after = self.wait_for_ports(target, required=(6000, 6500), timeout_sec=10)

        if not after["camera_6500"]:
            camera = self.run_script("start_car_camera_ssh.ps1", target, timeout_sec=18)
            commands.append(camera)
            after = self.wait_for_ports(target, required=(6000,), optional=(6500, 8080), timeout_sec=6)

        ok = after["control_6000"] and (after["camera_6500"] or after["camera_8080"])
        return {
            "ok": ok,
            "host": target,
            "before": before,
            "after": after,
            "commands": commands,
            "error": "" if ok else "Control or camera service did not open after SSH recovery.",
        }

    def wait_for_ports(
        self,
        host: str,
        required: tuple[int, ...],
        optional: tuple[int, ...] = (),
        timeout_sec: float = 12,
    ) -> dict[str, bool]:
        deadline = time.monotonic() + timeout_sec
        status = self.check_ports(host)
        while time.monotonic() < deadline:
            status = self.check_ports(host)
            required_ok = all(status[self.port_key(port)] for port in required)
            optional_ok = not optional or any(status[self.port_key(port)] for port in optional)
            if required_ok and optional_ok:
                return status
            time.sleep(0.8)
        return status

    def run_script(
        self,
        script_name: str,
        host: str,
        timeout_sec: float,
        extra_args: list[str] | None = None,
    ) -> dict[str, Any]:
        script = self.scripts_dir / script_name
        if not script.exists():
            return {"script": script_name, "ok": False, "error": f"script not found: {script}"}

        command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-CarHost",
            host,
        ]
        if extra_args:
            command.extend(extra_args)
        try:
            completed = subprocess.run(
                command,
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as exc:
            return {"script": script_name, "ok": False, "error": str(exc)}

        return {
            "script": script_name,
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-3000:],
            "stderr": completed.stderr[-1500:],
        }

    def port_key(self, port: int) -> str:
        return {
            22: "ssh_22",
            6000: "control_6000",
            6001: "bridge_6001",
            6500: "camera_6500",
            8080: "camera_8080",
        }[port]
