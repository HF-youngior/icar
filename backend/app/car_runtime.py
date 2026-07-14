from __future__ import annotations

import json
import base64
import os
import shlex
import socket
import subprocess
import time
import uuid
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
enabled = bool({1 if enabled else 0})
left_light = 1 if enabled else 0
right_light = 1 if enabled else 0
duration_ms = 0
methods = []
errors = []
available_light_methods = [
    name for name in dir(bot)
    if any(word in name.lower() for word in ("light", "lamp", "led", "rgb", "color"))
]

def try_call(name, arg_sets):
    method = getattr(bot, name, None)
    if not callable(method):
        return False
    for args in arg_sets:
        try:
            method(*args)
            methods.append(f"{{name}}{{args}}")
            time.sleep(0.02)
            return True
        except TypeError:
            continue
        except Exception as exc:
            errors.append(f"{{name}}{{args}}: {{exc}}")
            return False
    errors.append(f"{{name}}: no compatible signature")
    return False

for led_id in (0, 1, 2, 3, 4, 5, 0xFF):
    for name in (
        "set_colorful_lamps",
        "set_colorful_lamp",
        "set_rgb_lamp",
        "set_rgb",
        "set_led",
        "set_light",
        "set_lamp",
    ):
        try_call(name, ((led_id, red, green, blue), (red, green, blue), (led_id, enabled), (enabled,), (1 if enabled else 0,)))

for name in ("set_colorful_effect", "set_rgb_effect", "set_light_effect"):
    if try_call(name, ((effect, speed, 255), (effect, speed), (effect,))):
        break

for name in ("set_car_light", "set_car_lights", "set_headlight", "set_headlights"):
    try_call(name, ((enabled,), (1 if enabled else 0,), (enabled, enabled), (1 if enabled else 0, 1 if enabled else 0)))

if enabled:
    no_arg_names = (
        "set_on_left_light",
        "set_on_right_light",
        "left_light_on",
        "right_light_on",
        "turn_on_left_light",
        "turn_on_right_light",
    )
else:
    no_arg_names = (
        "set_off_left_light",
        "set_off_right_light",
        "left_light_off",
        "right_light_off",
        "turn_off_left_light",
        "turn_off_right_light",
    )
for name in no_arg_names:
    try_call(name, ((),))

for name in ("set_left_light", "set_right_light", "set_front_light", "set_rear_light", "set_head_light", "set_tail_light"):
    try_call(name, ((enabled,), (1 if enabled else 0,)))

def raw_protocol_frame(func, params):
    length = len(params) + 3
    body = [length, func] + list(params)
    checksum = sum(body) & 0xFF
    return bytes([0xFF, 0xFC] + body + [checksum])

def try_raw_sender(frame, label):
    hex_frame = frame.hex(" ").upper()
    for name in ("send_data", "send_cmd", "send_command", "uart_send", "serial_write", "_write_data", "write_data"):
        method = getattr(bot, name, None)
        if not callable(method):
            continue
        for args in ((frame,), (list(frame),), (bytearray(frame),)):
            try:
                method(*args)
                methods.append(f"{{name}}({{label}}:{{hex_frame}})")
                time.sleep(0.02)
                return True
            except TypeError:
                continue
            except Exception as exc:
                errors.append(f"{{name}}({{label}}): {{exc}}")
                break
    for attr in ("ser", "serial", "uart", "_serial", "_Rosmaster__ser"):
        stream = getattr(bot, attr, None)
        writer = getattr(stream, "write", None)
        if not callable(writer):
            continue
        try:
            writer(frame)
            methods.append(f"{{attr}}.write({{label}}:{{hex_frame}})")
            time.sleep(0.02)
            return True
        except Exception as exc:
            errors.append(f"{{attr}}.write({{label}}): {{exc}}")
    return False

try_raw_sender(raw_protocol_frame(0x05, [left_light, right_light, duration_ms & 0xFF, (duration_ms >> 8) & 0xFF]), "FUNC_RGB_HEADLIGHTS")
try_raw_sender(raw_protocol_frame(0x06, [effect, speed]), "FUNC_RGB_EFFECT")

ok = bool(methods)
print(json.dumps({{"ok": ok, "enabled": enabled, "rgb": [red, green, blue], "effect": effect, "methods": methods, "available_light_methods": available_light_methods[:40], "errors": errors[-8:]}}))
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

    def play_voice(self, *, text: str = "主人，我在", volume_percent: int = 85, host: str | None = None) -> dict[str, Any]:
        target = host or self.config.car.host
        phrase = str(text or "主人，我在")[:80]
        volume = max(0, min(100, int(volume_percent)))
        cloud_tts_error = ""
        cloud_tts = self._synthesize_tencent_tts(phrase, volume)
        if cloud_tts.get("ok"):
            cloud_result = self._play_cloud_tts_audio(
                audio_bytes=cloud_tts["audio"],
                codec=cloud_tts["codec"],
                target=target,
                volume_percent=volume,
            )
            if cloud_result.get("ok"):
                return {
                    "ok": True,
                    "adapter": "ssh-rosmaster",
                    "action": "voice",
                    "host": target,
                    "text": phrase,
                    "volume_percent": volume,
                    "spoken": True,
                    "engine": f"tencent-tts/{cloud_tts['codec']}",
                    "message": "Tencent Cloud TTS audio was uploaded to the car and played.",
                    "stdout": cloud_result.get("stdout", "")[-1600:],
                    "stderr": cloud_result.get("stderr", "")[-1200:],
                    "returncode": cloud_result.get("returncode", 0),
                }
            cloud_tts_error = cloud_result.get("message") or cloud_result.get("stderr") or "cloud TTS playback failed"
        elif cloud_tts.get("message"):
            cloud_tts_error = str(cloud_tts.get("message", ""))

        quoted_text = shlex.quote(phrase)
        script = f"""
export ICAR_VOICE_TEXT={quoted_text}
export ICAR_VOICE_VOLUME={volume}
python3 - <<'PY'
import os
import sys
sys.exit(0 if any(ord(ch) > 127 for ch in os.environ.get("ICAR_VOICE_TEXT", "")) else 1)
PY
if [ "$?" = "0" ]; then
  ICAR_VOICE_NON_ASCII=1
else
  ICAR_VOICE_NON_ASCII=0
fi
if command -v amixer >/dev/null 2>&1; then
  amixer set Master "$ICAR_VOICE_VOLUME%" unmute >/tmp/icar_voice_volume.log 2>&1 || true
  amixer set PCM "$ICAR_VOICE_VOLUME%" unmute >>/tmp/icar_voice_volume.log 2>&1 || true
  amixer set Speaker "$ICAR_VOICE_VOLUME%" unmute >>/tmp/icar_voice_volume.log 2>&1 || true
fi
if command -v pactl >/dev/null 2>&1; then
  pactl set-sink-mute @DEFAULT_SINK@ 0 >/tmp/icar_voice_pulse.log 2>&1 || true
  pactl set-sink-volume @DEFAULT_SINK@ "$ICAR_VOICE_VOLUME%" >>/tmp/icar_voice_pulse.log 2>&1 || true
fi
if [ "$ICAR_VOICE_NON_ASCII" = "1" ] && command -v ekho >/dev/null 2>&1; then
  ekho "$ICAR_VOICE_TEXT" >/tmp/icar_voice_ekho.log 2>&1 && echo '{{"ok": true, "spoken": true, "engine": "ekho"}}' && exit 0
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
if [ "$ICAR_VOICE_NON_ASCII" != "1" ] || [ "$ICAR_ALLOW_NON_CHINESE_TTS" = "1" ]; then
  if command -v spd-say >/dev/null 2>&1; then
    spd-say --wait --language zh -r -15 -i 100 "$ICAR_VOICE_TEXT" >/tmp/icar_voice_spd.log 2>&1 && echo '{{"ok": true, "spoken": true, "engine": "spd-say-wait"}}' && exit 0
  fi
  if command -v espeak-ng >/dev/null 2>&1; then
    espeak-ng -v zh "$ICAR_VOICE_TEXT" >/dev/null 2>&1 && echo '{{"ok": true, "spoken": true, "engine": "espeak-ng"}}' && exit 0
  fi
  if command -v espeak >/dev/null 2>&1; then
    espeak "$ICAR_VOICE_TEXT" >/dev/null 2>&1 && echo '{{"ok": true, "spoken": true, "engine": "espeak"}}' && exit 0
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
            "volume_percent": volume,
            "spoken": bool(parsed.get("spoken", False)),
            "engine": parsed.get("engine", "unknown"),
            "message": parsed.get("message") or parsed.get("error") or cloud_tts_error or "",
            "stdout": result["stdout"][-1600:],
            "stderr": result["stderr"][-1200:],
            "returncode": result["returncode"],
        }

    def _synthesize_tencent_tts(self, text: str, volume_percent: int) -> dict[str, Any]:
        secret_id = os.getenv("TENCENT_SECRET_ID", "")
        secret_key = os.getenv("TENCENT_SECRET_KEY", "")
        if not secret_id or not secret_key:
            return {"ok": False, "message": "Tencent Cloud credentials are not configured."}
        try:
            from tencentcloud.common import credential
            from tencentcloud.common.profile.client_profile import ClientProfile
            from tencentcloud.common.profile.http_profile import HttpProfile
            from tencentcloud.tts.v20190823 import models, tts_client
        except ImportError as exc:
            return {"ok": False, "message": f"Tencent Cloud SDK is not installed: {exc}"}

        def int_env(name: str, default: int) -> int:
            try:
                return int(float(os.getenv(name, str(default)) or default))
            except ValueError:
                return default

        codec = os.getenv("TENCENT_TTS_CODEC", "wav").strip().lower() or "wav"
        if codec not in {"wav", "mp3"}:
            codec = "wav"
        region = os.getenv("TENCENT_TTS_REGION", os.getenv("TENCENT_ASR_REGION", "ap-beijing"))
        http_profile = HttpProfile()
        http_profile.endpoint = "tts.tencentcloudapi.com"
        client_profile = ClientProfile()
        client_profile.httpProfile = http_profile
        client = tts_client.TtsClient(credential.Credential(secret_id, secret_key), region, client_profile)
        request_payload = {
            "Text": text,
            "SessionId": f"icar-{uuid.uuid4().hex}",
            "Volume": int_env("TENCENT_TTS_VOLUME", max(0, min(10, round(volume_percent / 10)))),
            "Speed": int_env("TENCENT_TTS_SPEED", 0),
            "ProjectId": int_env("TENCENT_TTS_PROJECT_ID", 0),
            "ModelType": int_env("TENCENT_TTS_MODEL_TYPE", 1),
            "VoiceType": int_env("TENCENT_TTS_VOICE_TYPE", 101001),
            "PrimaryLanguage": int_env("TENCENT_TTS_PRIMARY_LANGUAGE", 1),
            "SampleRate": int_env("TENCENT_TTS_SAMPLE_RATE", 16000),
            "Codec": codec,
        }
        try:
            req = models.TextToVoiceRequest()
            req.from_json_string(json.dumps(request_payload, ensure_ascii=False))
            resp = client.TextToVoice(req)
            data = json.loads(resp.to_json_string())
            audio = base64.b64decode(data.get("Audio", ""))
            if not audio:
                return {"ok": False, "message": f"Tencent TTS returned empty audio: {data.get('RequestId', '')}"}
            return {"ok": True, "audio": audio, "codec": codec, "request_id": data.get("RequestId", "")}
        except Exception as exc:
            return {"ok": False, "message": f"Tencent TTS failed: {exc}"}

    def _play_cloud_tts_audio(
        self,
        *,
        audio_bytes: bytes,
        codec: str,
        target: str,
        volume_percent: int,
    ) -> dict[str, Any]:
        temp_dir = PROJECT_ROOT / "data" / "tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        suffix = ".mp3" if codec == "mp3" else ".wav"
        local_path = temp_dir / f"icar_tts_{uuid.uuid4().hex}{suffix}"
        remote_path = f"/tmp/icar_tts_{uuid.uuid4().hex}{suffix}"
        try:
            local_path.write_bytes(audio_bytes)
            copy_result = self._copy_to_car(local_path, remote_path, target, timeout_sec=12)
            if not copy_result.get("ok"):
                return {
                    "ok": False,
                    "message": copy_result.get("stderr") or copy_result.get("stdout") or "failed to upload TTS audio to car",
                    **copy_result,
                }
            script = f"""
export ICAR_VOICE_FILE={shlex.quote(remote_path)}
export ICAR_VOICE_CODEC={shlex.quote(codec)}
export ICAR_VOICE_VOLUME={max(0, min(100, int(volume_percent)))}
if command -v amixer >/dev/null 2>&1; then
  amixer set Master "$ICAR_VOICE_VOLUME%" unmute >/tmp/icar_voice_volume.log 2>&1 || true
  amixer set PCM "$ICAR_VOICE_VOLUME%" unmute >>/tmp/icar_voice_volume.log 2>&1 || true
  amixer set Speaker "$ICAR_VOICE_VOLUME%" unmute >>/tmp/icar_voice_volume.log 2>&1 || true
fi
if [ "$ICAR_VOICE_CODEC" = "wav" ] && command -v aplay >/dev/null 2>&1; then
  aplay -q "$ICAR_VOICE_FILE" >/tmp/icar_voice_cloud_tts.log 2>&1
  code=$?
elif [ "$ICAR_VOICE_CODEC" = "wav" ] && command -v paplay >/dev/null 2>&1; then
  paplay "$ICAR_VOICE_FILE" >/tmp/icar_voice_cloud_tts.log 2>&1
  code=$?
elif [ "$ICAR_VOICE_CODEC" = "wav" ] && command -v pw-play >/dev/null 2>&1; then
  pw-play "$ICAR_VOICE_FILE" >/tmp/icar_voice_cloud_tts.log 2>&1
  code=$?
elif [ "$ICAR_VOICE_CODEC" = "mp3" ] && command -v mpg123 >/dev/null 2>&1; then
  mpg123 -q "$ICAR_VOICE_FILE" >/tmp/icar_voice_cloud_tts.log 2>&1
  code=$?
elif command -v ffplay >/dev/null 2>&1; then
  ffplay -nodisp -autoexit -loglevel quiet "$ICAR_VOICE_FILE" >/tmp/icar_voice_cloud_tts.log 2>&1
  code=$?
else
  echo '{{"ok": false, "engine": "tencent-tts-upload", "error": "No audio player found on car."}}'
  rm -f "$ICAR_VOICE_FILE"
  exit 2
fi
rm -f "$ICAR_VOICE_FILE"
if [ "$code" = "0" ]; then
  echo '{{"ok": true, "spoken": true, "engine": "tencent-tts-upload"}}'
else
  echo '{{"ok": false, "engine": "tencent-tts-upload", "error": "audio player failed"}}'
fi
exit "$code"
"""
            result = self._ssh(script, target, timeout_sec=15, tolerate=True)
            parsed = self._last_json_line(result.get("stdout", ""))
            return {
                "ok": result["ok"] and bool(parsed.get("ok", False)),
                "message": parsed.get("error") or "",
                **result,
            }
        finally:
            try:
                local_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _copy_to_car(self, local_path: Path, remote_path: str, host: str, timeout_sec: float) -> dict[str, Any]:
        executable = Path(r"C:\Program Files\PuTTY\pscp.exe")
        target = f"{self.user}@{host}:{remote_path}"
        if executable.exists():
            command = [
                str(executable),
                "-batch",
                "-hostkey",
                self.host_key,
                "-pw",
                self.password,
                str(local_path),
                target,
            ]
        else:
            command = [
                "scp",
                "-o",
                "ConnectTimeout=8",
                "-o",
                "StrictHostKeyChecking=accept-new",
                str(local_path),
                target,
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
            return {
                "ok": completed.returncode == 0,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        except Exception as exc:
            return {"ok": False, "returncode": -1, "stdout": "", "stderr": str(exc)}

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
