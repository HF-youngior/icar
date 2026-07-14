from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT


@dataclass
class TtsSettings:
    secret_id: str = os.getenv("TENCENT_SECRET_ID", "")
    secret_key: str = os.getenv("TENCENT_SECRET_KEY", "")
    region: str = os.getenv("TENCENT_TTS_REGION", os.getenv("TENCENT_ASR_REGION", "ap-beijing"))
    project_id: int = int(os.getenv("TENCENT_TTS_PROJECT_ID", os.getenv("TENCENT_ASR_PROJECT_ID", "0")))
    voice_type: int = int(os.getenv("TENCENT_TTS_VOICE_TYPE", "101001"))
    codec: str = os.getenv("TENCENT_TTS_CODEC", "wav")
    sample_rate: int = int(os.getenv("TENCENT_TTS_SAMPLE_RATE", "16000"))
    primary_language: int = int(os.getenv("TENCENT_TTS_PRIMARY_LANGUAGE", "1"))
    model_type: int = int(os.getenv("TENCENT_TTS_MODEL_TYPE", "1"))
    speed: float = float(os.getenv("TENCENT_TTS_SPEED", "0"))
    volume: float = float(os.getenv("TENCENT_TTS_VOLUME", "0"))
    callback_base_url: str = os.getenv("TENCENT_TTS_CALLBACK_BASE_URL", "").strip()


class TencentTtsService:
    def __init__(self) -> None:
        self.settings = TtsSettings()
        self.data_dir = PROJECT_ROOT / "data" / "tts"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_dir = self.data_dir / "tasks"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir = self.data_dir / "audio"
        self.audio_dir.mkdir(parents=True, exist_ok=True)

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "configured": bool(self.settings.secret_id and self.settings.secret_key),
            "region": self.settings.region,
            "project_id": self.settings.project_id,
            "voice_type": self.settings.voice_type,
            "codec": self.settings.codec,
            "sample_rate": self.settings.sample_rate,
            "callback_base_url": self.settings.callback_base_url,
            "callback_enabled": bool(self.settings.callback_base_url),
            "tasks_dir": str(self.tasks_dir),
            "audio_dir": str(self.audio_dir),
        }

    def _build_client(self):
        try:
            from tencentcloud.common import credential
            from tencentcloud.common.profile.client_profile import ClientProfile
            from tencentcloud.common.profile.http_profile import HttpProfile
            from tencentcloud.tts.v20190823 import models, tts_client
        except ImportError as exc:
            raise RuntimeError(
                "Tencent TTS SDK is not installed. Run `pip install -r backend/requirements.txt` first."
            ) from exc

        if not self.settings.secret_id or not self.settings.secret_key:
            raise RuntimeError("Tencent TTS credentials are missing in .env.")

        http_profile = HttpProfile()
        http_profile.endpoint = "tts.tencentcloudapi.com"
        client_profile = ClientProfile()
        client_profile.httpProfile = http_profile
        cred = credential.Credential(self.settings.secret_id, self.settings.secret_key)
        client = tts_client.TtsClient(cred, self.settings.region, client_profile)
        return client, models

    def _task_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id}.json"

    def _save_task(self, task: dict[str, Any]) -> dict[str, Any]:
        task_id = str(task["task_id"])
        self._task_path(task_id).write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
        return task

    def _load_task(self, task_id: str) -> dict[str, Any] | None:
        path = self._task_path(task_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _callback_url(self) -> str:
        base = self.settings.callback_base_url.rstrip("/")
        if not base:
            return ""
        return f"{base}/api/tts/tencent/callback"

    def submit_task(self, text: str, *, source: str = "llm") -> dict[str, Any]:
        normalized_text = str(text).strip()
        if not normalized_text:
            raise ValueError("text is required")

        client, models = self._build_client()
        payload: dict[str, Any] = {
            "Text": normalized_text,
            "Volume": self.settings.volume,
            "Speed": self.settings.speed,
            "ProjectId": self.settings.project_id,
            "ModelType": self.settings.model_type,
            "VoiceType": self.settings.voice_type,
            "PrimaryLanguage": self.settings.primary_language,
            "SampleRate": self.settings.sample_rate,
            "Codec": self.settings.codec,
        }
        callback_url = self._callback_url()
        if callback_url:
            payload["CallbackUrl"] = callback_url

        req = models.CreateTtsTaskRequest()
        req.from_json_string(json.dumps(payload))
        resp = client.CreateTtsTask(req)
        data = json.loads(resp.to_json_string())
        task_id = (
            data.get("Data", {}).get("TaskId")
            or data.get("Response", {}).get("Data", {}).get("TaskId")
        )
        if not task_id:
            raise RuntimeError(f"Tencent TTS did not return TaskId: {data}")

        task = {
            "task_id": str(task_id),
            "text": normalized_text,
            "source": source,
            "status": 0,
            "status_str": "submitted",
            "result_url": "",
            "audio_file": "",
            "error_msg": "",
            "codec": self.settings.codec,
            "voice_type": self.settings.voice_type,
            "sample_rate": self.settings.sample_rate,
            "callback_url": callback_url,
            "created_request_id": data.get("RequestId") or data.get("Response", {}).get("RequestId", ""),
            "callback_received": False,
        }
        self._save_task(task)
        return task

    def query_task(self, task_id: str) -> dict[str, Any]:
        client, models = self._build_client()
        req = models.DescribeTtsTaskStatusRequest()
        req.from_json_string(json.dumps({"TaskId": str(task_id)}))
        resp = client.DescribeTtsTaskStatus(req)
        data = json.loads(resp.to_json_string())
        status_data = data.get("Data") or data.get("Response", {}).get("Data", {}) or {}

        task = self._load_task(str(task_id)) or {"task_id": str(task_id)}
        task.update(
            {
                "status": status_data.get("Status"),
                "status_str": status_data.get("StatusStr", ""),
                "result_url": status_data.get("ResultUrl", ""),
                "error_msg": status_data.get("ErrorMsg", ""),
                "last_query_request_id": data.get("RequestId") or data.get("Response", {}).get("RequestId", ""),
            }
        )
        if task.get("status") == 2 and task.get("result_url") and not task.get("audio_file"):
            self._download_audio(task)
        self._save_task(task)
        return task

    def _download_audio(self, task: dict[str, Any]) -> dict[str, Any]:
        result_url = str(task.get("result_url", "")).strip()
        if not result_url:
            return task

        suffix = str(task.get("codec") or self.settings.codec or "wav").lower()
        audio_path = self.audio_dir / f"{task['task_id']}.{suffix}"
        try:
            request = urllib.request.Request(result_url, headers={"User-Agent": "iCar-TTS/1.0"})
            with urllib.request.urlopen(request, timeout=60) as response:
                audio_path.write_bytes(response.read())
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            task["download_error"] = str(exc)
            return task

        task["audio_file"] = str(audio_path)
        task["download_error"] = ""
        return task

    def handle_callback_form(self, raw_body: bytes) -> dict[str, Any]:
        text = raw_body.decode("utf-8", errors="replace")
        form = urllib.parse.parse_qs(text, keep_blank_values=True)
        raw_data = form.get("data", ["{}"])[0]
        payload = json.loads(raw_data)

        task_id = str(payload.get("TaskId", "")).strip()
        if not task_id:
            raise ValueError("Tencent TTS callback is missing TaskId")

        task = self._load_task(task_id) or {"task_id": task_id}
        task.update(
            {
                "status": payload.get("Status"),
                "status_str": payload.get("StatusStr", ""),
                "result_url": payload.get("ResultUrl", ""),
                "error_msg": payload.get("ErrorMsg", ""),
                "callback_received": True,
                "callback_payload": payload,
            }
        )
        if task.get("status") == 2 and task.get("result_url"):
            self._download_audio(task)
        self._save_task(task)
        return task

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return self._load_task(task_id)

    def list_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in sorted(self.tasks_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                items.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
            if len(items) >= limit:
                break
        return items
