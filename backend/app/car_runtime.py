from __future__ import annotations

import json
import shlex
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
        self.user = "jetson"
        self.password = "yahboom"
        self.host_key = "ssh-ed25519 255 SHA256:AJffjk3YWwStux7ZbdKdft3teC8b7Jsubuvv4zMYuD8"

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

    def auxiliary_control(self, action: str, **values: Any) -> dict[str, Any]:
        if action == "light":
            return self.control_light(**values)
        if action == "voice":
            return self.play_voice(**values)
        raise ValueError(f"Unsupported runtime auxiliary action: {action}")

    def control_light(
        self,
        *,
        enabled: bool = True,
        r: int = 38,
        g: int = 244,
        b: int = 255,
        host: str | None = None,
    ) -> dict[str, Any]:
        target = host or self.config.car.host
        red = self._clamp_byte(r if enabled else 0)
        green = self._clamp_byte(g if enabled else 0)
        blue = self._clamp_byte(b if enabled else 0)
        effect = 1 if enabled else 0
        speed = 80 if enabled else 0
        script = f"""
cd /home/jetson/Rosmaster-App/rosmaster 2>/dev/null || cd /home/jetson
python3 - <<'PY'
import json
import sys
import time

sys.path.insert(0, "/home/jetson/Rosmaster-App/rosmaster")
from Rosmaster_Lib import Rosmaster

bot = Rosmaster()
red, green, blue = {red}, {green}, {blue}
effect, speed = {effect}, {speed}
methods = []
errors = []
for led_id in (0, 1, 2, 3, 4, 5, 0xFF):
    try:
        bot.set_colorful_lamps(led_id, red, green, blue)
        methods.append(f"set_colorful_lamps({{led_id}})")
        time.sleep(0.02)
    except Exception as exc:
        errors.append(f"lamp {{led_id}}: {{exc}}")
for args in ((effect, speed, 255), (effect, speed)):
    try:
        bot.set_colorful_effect(*args)
        methods.append(f"set_colorful_effect/{{len(args)}}")
        break
    except Exception as exc:
        errors.append(f"effect {{args}}: {{exc}}")
ok = bool(methods)
print(json.dumps({{"ok": ok, "enabled": bool({1 if enabled else 0}), "rgb": [red, green, blue], "effect": effect, "methods": methods, "errors": errors[-4:]}}))
sys.exit(0 if ok else 2)
PY
"""
        result = self._ssh(script, target, timeout_sec=7, tolerate=True)
        parsed = self._last_json_line(result["stdout"])
        return {
            "ok": result["ok"] and bool(parsed.get("ok", False)),
            "adapter": "ssh-rosmaster",
            "action": "light",
            "host": target,
            "enabled": enabled,
            "rgb": [red, green, blue],
            "stdout": result["stdout"][-1600:],
            "stderr": result["stderr"][-1200:],
            "returncode": result["returncode"],
            **({"result": parsed} if parsed else {}),
        }

    def play_voice(self, *, text: str = "主人，我在", host: str | None = None) -> dict[str, Any]:
        target = host or self.config.car.host
        phrase = str(text or "主人，我在")[:80]
        quoted_text = shlex.quote(phrase)
        script = f"""
export ICAR_VOICE_TEXT={quoted_text}
if command -v spd-say >/dev/null 2>&1; then
  spd-say --wait --language zh -r -15 -i 100 "$ICAR_VOICE_TEXT" >/tmp/icar_voice_spd.log 2>&1 && echo '{{"ok": true, "spoken": true, "engine": "spd-say-wait"}}' && exit 0
fi
if command -v espeak-ng >/dev/null 2>&1; then
  espeak-ng -v zh "$ICAR_VOICE_TEXT" >/dev/null 2>&1 && echo '{{"ok": true, "spoken": true, "engine": "espeak-ng"}}' && exit 0
fi
if command -v espeak >/dev/null 2>&1; then
  espeak "$ICAR_VOICE_TEXT" >/dev/null 2>&1 && echo '{{"ok": true, "spoken": true, "engine": "espeak"}}' && exit 0
fi
if command -v pico2wave >/dev/null 2>&1 && command -v aplay >/dev/null 2>&1; then
  pico2wave -l zh-CN -w /tmp/icar_voice.wav "$ICAR_VOICE_TEXT" >/dev/null 2>&1 && aplay -q /tmp/icar_voice.wav >/dev/null 2>&1 && echo '{{"ok": true, "spoken": true, "engine": "pico2wave"}}' && exit 0
fi
if command -v sherpa-onnx-offline-tts-play-alsa >/dev/null 2>&1; then
  model="$(find /home/jetson /opt /usr/local -maxdepth 7 -type f -name '*.onnx' 2>/dev/null | head -n 1)"
  tokens="$(find /home/jetson /opt /usr/local -maxdepth 7 -type f -name 'tokens.txt' 2>/dev/null | head -n 1)"
  if [ -n "$model" ] && [ -n "$tokens" ]; then
    sherpa-onnx-offline-tts-play-alsa --vits-model="$model" --vits-tokens="$tokens" "$ICAR_VOICE_TEXT" >/dev/null 2>&1 && echo '{{"ok": true, "spoken": true, "engine": "sherpa-onnx"}}' && exit 0
  fi
fi
cd /home/jetson/Rosmaster-App/rosmaster 2>/dev/null || cd /home/jetson
python3 - <<'PY'
import json
import sys
import time

sys.path.insert(0, "/home/jetson/Rosmaster-App/rosmaster")
try:
    from Rosmaster_Lib import Rosmaster
    bot = Rosmaster()
    for duration in (120, 80, 120):
        bot.set_beep(duration)
        time.sleep(0.12)
    print(json.dumps({{"ok": True, "spoken": False, "engine": "beep-fallback", "message": "No local TTS engine was found on the car; used beep fallback."}}))
except Exception as exc:
    print(json.dumps({{"ok": False, "spoken": False, "engine": "none", "error": str(exc)}}))
    sys.exit(2)
PY
"""
        result = self._ssh(script, target, timeout_sec=12, tolerate=True)
        parsed = self._last_json_line(result["stdout"])
        ok = result["ok"] and bool(parsed.get("ok", False))
        return {
            "ok": ok,
            "adapter": "ssh-rosmaster",
            "action": "voice",
            "host": target,
            "text": phrase,
            "spoken": bool(parsed.get("spoken", False)),
            "engine": parsed.get("engine", "unknown"),
            "message": parsed.get("message") or parsed.get("error") or "",
            "stdout": result["stdout"][-1600:],
            "stderr": result["stderr"][-1200:],
            "returncode": result["returncode"],
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

    def _ssh(self, script: str, host: str, timeout_sec: float, tolerate: bool = False) -> dict[str, Any]:
        executable = Path(r"C:\Program Files\PuTTY\plink.exe")
        target = f"{self.user}@{host}"
        if executable.exists():
            command = [
                str(executable),
                "-batch",
                "-hostkey",
                self.host_key,
                "-pw",
                self.password,
                target,
                f"bash -lc {shlex.quote(script)}",
            ]
        else:
            command = [
                "ssh",
                "-o",
                "ConnectTimeout=8",
                "-o",
                "ServerAliveInterval=15",
                "-o",
                "StrictHostKeyChecking=accept-new",
                target,
                f"bash -lc {shlex.quote(script)}",
            ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_sec,
            )
            result = {
                "ok": completed.returncode == 0,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        except Exception as exc:
            result = {"ok": False, "returncode": -1, "stdout": "", "stderr": str(exc)}
        if not result["ok"] and not tolerate:
            raise RuntimeError(result["stderr"] or result["stdout"] or "remote command failed")
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

    def _clamp_byte(self, value: int) -> int:
        return max(0, min(255, int(value)))

    def port_key(self, port: int) -> str:
        return {
            22: "ssh_22",
            6000: "control_6000",
            6001: "bridge_6001",
            6500: "camera_6500",
            8080: "camera_8080",
        }[port]
