from __future__ import annotations

import base64
import hashlib
import json
import os
import shlex
import uuid
from pathlib import Path
from typing import Any

from .car_runtime import CarRuntimeRecovery
from .config import PROJECT_ROOT


class PreparedVoiceAssetService:
    manifest_name = "manifest.json"

    def __init__(
        self,
        runtime: CarRuntimeRecovery,
        prepared_voices: dict[str, dict[str, Any]],
        *,
        local_dir: Path | None = None,
        remote_dir: str | None = None,
    ) -> None:
        self.runtime = runtime
        self.prepared_voices = prepared_voices
        self.local_dir = local_dir or self._default_local_dir()
        self.remote_dir = (remote_dir or os.getenv("PREPARED_VOICE_REMOTE_DIR", "/home/jetson/icar/prepared_voice")).rstrip("/")

    @staticmethod
    def _default_local_dir() -> Path:
        configured = os.getenv("PREPARED_VOICE_LOCAL_DIR", "").strip()
        if configured:
            path = Path(configured)
            return path if path.is_absolute() else PROJECT_ROOT / path
        return PROJECT_ROOT / "data" / "prepared_voice"

    @staticmethod
    def llm_visible_voices(prepared_voices: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
        visible: dict[str, dict[str, str]] = {}
        for key, item in prepared_voices.items():
            if not item.get("exposed_to_llm", False):
                continue
            visible[key] = {
                "text": str(item.get("text", "")),
                "description": str(item.get("description", "")),
            }
        return visible

    def manifest_path(self) -> Path:
        return self.local_dir / self.manifest_name

    def voice_path(self, key: str) -> Path:
        voice = self.prepared_voices[key]
        return self.local_dir / str(voice["filename"])

    def build_manifest(self) -> dict[str, Any]:
        voices: dict[str, Any] = {}
        for key, item in self.prepared_voices.items():
            filename = str(item["filename"])
            path = self.local_dir / filename
            exists = path.exists()
            voices[key] = {
                "text": str(item.get("text", "")),
                "description": str(item.get("description", "")),
                "filename": filename,
                "exposed_to_llm": bool(item.get("exposed_to_llm", False)),
                "sha256": self._sha256(path) if exists else "",
                "bytes": path.stat().st_size if exists else 0,
            }
        return {
            "version": "prepared-voice-v1",
            "codec": self._codec(),
            "voices": voices,
        }

    def write_manifest(self) -> dict[str, Any]:
        self.local_dir.mkdir(parents=True, exist_ok=True)
        manifest = self.build_manifest()
        self.manifest_path().write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    def generate_local_assets(self, *, overwrite: bool = False) -> dict[str, Any]:
        self.local_dir.mkdir(parents=True, exist_ok=True)
        generated: list[str] = []
        skipped: list[str] = []
        errors: dict[str, str] = {}
        for key, item in self.prepared_voices.items():
            path = self.voice_path(key)
            if path.exists() and not overwrite:
                skipped.append(key)
                continue
            result = self._synthesize_tencent_tts(str(item.get("text", "")))
            if not result.get("ok"):
                errors[key] = str(result.get("message", "TTS failed"))
                continue
            path.write_bytes(result["audio"])
            generated.append(key)
        manifest = self.write_manifest()
        return {
            "ok": not errors,
            "local_dir": str(self.local_dir),
            "generated": generated,
            "skipped": skipped,
            "errors": errors,
            "manifest": manifest,
        }

    def ensure_synced(self, *, host: str | None = None) -> dict[str, Any]:
        target = host or self.runtime.config.car.host
        local_manifest = self.write_manifest()
        mkdir_result = self.runtime._ssh(
            f"mkdir -p {shlex.quote(self.remote_dir)}",
            target,
            timeout_sec=8,
            tolerate=True,
        )
        if not mkdir_result.get("ok"):
            return {
                "ok": False,
                "host": target,
                "remote_dir": self.remote_dir,
                "message": mkdir_result.get("stderr") or mkdir_result.get("stdout") or "failed to create remote voice dir",
                "mkdir": mkdir_result,
            }

        remote_manifest = self._read_remote_manifest(target)
        remote_voices = remote_manifest.get("voices", {}) if isinstance(remote_manifest, dict) else {}
        uploaded: list[str] = []
        skipped: list[str] = []
        missing_local: list[str] = []
        errors: dict[str, str] = {}

        for key, item in local_manifest["voices"].items():
            local_path = self.local_dir / item["filename"]
            if not local_path.exists() or not item.get("sha256"):
                missing_local.append(key)
                continue
            remote_item = remote_voices.get(key, {}) if isinstance(remote_voices, dict) else {}
            if (
                remote_item.get("filename") == item["filename"]
                and remote_item.get("sha256") == item["sha256"]
                and remote_item.get("bytes") == item["bytes"]
            ):
                skipped.append(key)
                continue
            copy = self.runtime._copy_to_car(
                local_path,
                f"{self.remote_dir}/{item['filename']}",
                target,
                timeout_sec=15,
            )
            if copy.get("ok"):
                uploaded.append(key)
            else:
                errors[key] = copy.get("stderr") or copy.get("stdout") or "upload failed"

        if not errors:
            manifest_copy = self.runtime._copy_to_car(
                self.manifest_path(),
                f"{self.remote_dir}/{self.manifest_name}",
                target,
                timeout_sec=10,
            )
            if not manifest_copy.get("ok"):
                errors[self.manifest_name] = manifest_copy.get("stderr") or manifest_copy.get("stdout") or "manifest upload failed"

        return {
            "ok": not errors,
            "host": target,
            "remote_dir": self.remote_dir,
            "uploaded": uploaded,
            "skipped": skipped,
            "missing_local": missing_local,
            "errors": errors,
        }

    def play_prepared(self, key: str, *, host: str | None = None, volume_percent: int = 85) -> dict[str, Any]:
        if key not in self.prepared_voices:
            return {"ok": False, "message": f"unknown prepared voice: {key}"}
        local_path = self.voice_path(key)
        if not local_path.exists():
            return {"ok": False, "message": f"local prepared voice is missing: {local_path}"}
        sync = self.ensure_synced(host=host)
        if not sync.get("ok"):
            return {"ok": False, "message": "prepared voice sync failed", "sync": sync}
        voice = self.prepared_voices[key]
        return {
            **self._play_remote_file(
                str(voice["filename"]),
                host=host,
                volume_percent=volume_percent,
            ),
            "sync": sync,
        }

    def _play_remote_file(self, filename: str, *, host: str | None = None, volume_percent: int = 85) -> dict[str, Any]:
        target = host or self.runtime.config.car.host
        remote_path = f"{self.remote_dir}/{filename}"
        codec = self._codec()
        volume = max(0, min(100, int(volume_percent)))
        script = f"""
export ICAR_VOICE_FILE={shlex.quote(remote_path)}
export ICAR_VOICE_CODEC={shlex.quote(codec)}
export ICAR_VOICE_VOLUME={volume}
if [ ! -f "$ICAR_VOICE_FILE" ]; then
  echo '{{"ok": false, "engine": "prepared-voice", "error": "prepared voice file missing"}}'
  exit 3
fi
if command -v amixer >/dev/null 2>&1; then
  amixer set Master "$ICAR_VOICE_VOLUME%" unmute >/tmp/icar_voice_volume.log 2>&1 || true
  amixer set PCM "$ICAR_VOICE_VOLUME%" unmute >>/tmp/icar_voice_volume.log 2>&1 || true
  amixer set Speaker "$ICAR_VOICE_VOLUME%" unmute >>/tmp/icar_voice_volume.log 2>&1 || true
fi
if [ "$ICAR_VOICE_CODEC" = "wav" ] && command -v aplay >/dev/null 2>&1; then
  aplay -q "$ICAR_VOICE_FILE" >/tmp/icar_prepared_voice.log 2>&1
  code=$?
elif [ "$ICAR_VOICE_CODEC" = "mp3" ] && command -v mpg123 >/dev/null 2>&1; then
  mpg123 -q "$ICAR_VOICE_FILE" >/tmp/icar_prepared_voice.log 2>&1
  code=$?
elif command -v ffplay >/dev/null 2>&1; then
  ffplay -nodisp -autoexit -loglevel quiet "$ICAR_VOICE_FILE" >/tmp/icar_prepared_voice.log 2>&1
  code=$?
else
  echo '{{"ok": false, "engine": "prepared-voice", "error": "No audio player found on car."}}'
  exit 2
fi
if [ "$code" = "0" ]; then
  echo '{{"ok": true, "spoken": true, "engine": "prepared-voice"}}'
else
  echo '{{"ok": false, "engine": "prepared-voice", "error": "audio player failed"}}'
fi
exit "$code"
"""
        result = self.runtime._ssh(script, target, timeout_sec=12, tolerate=True)
        parsed = self.runtime._last_json_line(result.get("stdout", ""))
        return {
            "ok": result.get("ok", False) and bool(parsed.get("ok", False)),
            "adapter": "ssh-rosmaster",
            "action": "prepared_voice",
            "host": target,
            "remote_path": remote_path,
            "spoken": bool(parsed.get("spoken", False)),
            "engine": parsed.get("engine", "prepared-voice"),
            "message": parsed.get("message") or parsed.get("error") or "",
            "stdout": result.get("stdout", "")[-1600:],
            "stderr": result.get("stderr", "")[-1200:],
            "returncode": result.get("returncode", 0),
        }

    def _read_remote_manifest(self, host: str) -> dict[str, Any]:
        result = self.runtime._ssh(
            f"cat {shlex.quote(self.remote_dir + '/' + self.manifest_name)} 2>/dev/null || echo '{{}}'",
            host,
            timeout_sec=8,
            tolerate=True,
        )
        text = result.get("stdout", "").strip()
        try:
            return json.loads(text or "{}")
        except json.JSONDecodeError:
            return {}

    def _synthesize_tencent_tts(self, text: str) -> dict[str, Any]:
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

        codec = self._codec()
        region = os.getenv("TENCENT_TTS_REGION", os.getenv("TENCENT_ASR_REGION", "ap-beijing"))
        http_profile = HttpProfile()
        http_profile.endpoint = "tts.tencentcloudapi.com"
        client_profile = ClientProfile()
        client_profile.httpProfile = http_profile
        client = tts_client.TtsClient(credential.Credential(secret_id, secret_key), region, client_profile)
        request_payload = {
            "Text": text,
            "SessionId": f"icar-prepared-{uuid.uuid4().hex}",
            "Volume": self._int_env("TENCENT_TTS_VOLUME", 0),
            "Speed": self._int_env("TENCENT_TTS_SPEED", 0),
            "ProjectId": self._int_env("TENCENT_TTS_PROJECT_ID", 0),
            "ModelType": self._int_env("TENCENT_TTS_MODEL_TYPE", 1),
            "VoiceType": self._int_env("TENCENT_TTS_VOICE_TYPE", 101001),
            "PrimaryLanguage": self._int_env("TENCENT_TTS_PRIMARY_LANGUAGE", 1),
            "SampleRate": self._int_env("TENCENT_TTS_SAMPLE_RATE", 16000),
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

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _codec() -> str:
        codec = os.getenv("TENCENT_TTS_CODEC", "wav").strip().lower() or "wav"
        return codec if codec in {"wav", "mp3"} else "wav"

    @staticmethod
    def _int_env(name: str, default: int) -> int:
        try:
            return int(float(os.getenv(name, str(default)) or default))
        except ValueError:
            return default
