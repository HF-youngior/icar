from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any


def _parse_env_list(raw_value: str, fallback: list[str]) -> list[str]:
    text = (raw_value or "").strip()
    if not text:
        return fallback
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    values = [item.strip().strip("\"'") for item in text.split(",")]
    return [item for item in values if item] or fallback


def _parse_env_map(raw_value: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for item in _parse_env_list(raw_value, []):
        if "=" not in item:
            continue
        source, target = item.split("=", 1)
        source = source.strip()
        target = target.strip()
        if source and target:
            pairs[source] = target
    return pairs


@dataclass
class VoiceSettings:
    wake_phrases: list[str] = None  # type: ignore[assignment]
    wake_replacements: dict[str, str] = None  # type: ignore[assignment]
    tencent_secret_id: str = os.getenv("TENCENT_SECRET_ID", "")
    tencent_secret_key: str = os.getenv("TENCENT_SECRET_KEY", "")
    tencent_app_id: str = os.getenv("TENCENT_ASR_APP_ID", "")
    tencent_region: str = os.getenv("TENCENT_ASR_REGION", "ap-beijing")
    tencent_engine_model_type: str = os.getenv("TENCENT_ASR_ENGINE_MODEL_TYPE", "16k_zh")
    tencent_project_id: int = int(os.getenv("TENCENT_ASR_PROJECT_ID", "0"))
    tencent_hotword_id: str = os.getenv("TENCENT_ASR_HOTWORD_ID", "")
    tencent_hotword_list: str = os.getenv("TENCENT_ASR_HOTWORD_LIST", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
    openai_model: str = os.getenv("OPENAI_MODEL", "deepseek-v4-pro")
    openai_temperature: float = float(os.getenv("OPENAI_TEMPERATURE", "0.5"))
    openai_thinking_type: str = os.getenv("OPENAI_THINKING_TYPE", "disabled")

    def __post_init__(self) -> None:
        self.wake_phrases = _parse_env_list(
            os.getenv("VOICE_WAKE_PHRASES", os.getenv("VOICE_WAKE_PHRASE", "小比")),
            ["小比"],
        )
        self.wake_phrases = sorted(set(self.wake_phrases), key=len, reverse=True)
        self.wake_replacements = _parse_env_map(os.getenv("VOICE_WAKE_REPLACEMENTS", ""))


class VoicePipeline:
    def __init__(self) -> None:
        self.settings = VoiceSettings()

    def health(self, tool_definitions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        tools = tool_definitions or []
        return {
            "ok": True,
            "tencent_configured": bool(self.settings.tencent_secret_id and self.settings.tencent_secret_key),
            "tencent_region": self.settings.tencent_region,
            "tencent_engine_model_type": self.settings.tencent_engine_model_type,
            "tencent_hotword_id_configured": bool(self.settings.tencent_hotword_id),
            "tencent_hotword_list_configured": bool(self.settings.tencent_hotword_list),
            "wake_phrases": self.settings.wake_phrases,
            "wake_replacements": self.settings.wake_replacements,
            "llm_configured": bool(self.settings.openai_api_key and self.settings.openai_model),
            "llm_model": self.settings.openai_model,
            "llm_base_url": self.settings.openai_base_url,
            "llm_temperature": self.settings.openai_temperature,
            "llm_thinking_type": self.settings.openai_thinking_type,
            "tool_names": [tool.get("name", "") for tool in tools],
        }

    def _parse_llm_json(self, output: str) -> dict[str, Any] | None:
        text = (output or "").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        if "```" in text:
            lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
            fenced = "\n".join(lines).strip()
            if fenced:
                try:
                    return json.loads(fenced)
                except json.JSONDecodeError:
                    return None
        return None

    def _build_tencent_client(self):
        try:
            from tencentcloud.asr.v20190614 import asr_client, models
            from tencentcloud.common import credential
            from tencentcloud.common.profile.client_profile import ClientProfile
            from tencentcloud.common.profile.http_profile import HttpProfile
        except ImportError as exc:
            raise RuntimeError(
                "Tencent ASR SDK is not installed. Run `pip install -r backend/requirements.txt` first."
            ) from exc

        if not self.settings.tencent_secret_id or not self.settings.tencent_secret_key:
            raise RuntimeError("Tencent ASR credentials are missing in .env.")

        http_profile = HttpProfile()
        http_profile.endpoint = "asr.tencentcloudapi.com"
        client_profile = ClientProfile()
        client_profile.httpProfile = http_profile
        cred = credential.Credential(
            self.settings.tencent_secret_id,
            self.settings.tencent_secret_key,
        )
        client = asr_client.AsrClient(cred, self.settings.tencent_region, client_profile)
        return client, models

    def recognize(self, audio_bytes: bytes, voice_format: str = "wav") -> dict[str, Any]:
        if not audio_bytes:
            raise RuntimeError("Audio payload is empty.")

        client, models = self._build_tencent_client()
        request_payload = {
            "ProjectId": self.settings.tencent_project_id,
            "SubServiceType": 2,
            "EngSerViceType": self.settings.tencent_engine_model_type,
            "SourceType": 1,
            "VoiceFormat": voice_format,
            "UsrAudioKey": str(uuid.uuid4()),
            "Data": base64.b64encode(audio_bytes).decode("utf-8"),
            "DataLen": len(audio_bytes),
            "FilterDirty": 0,
            "FilterModal": 0,
            "FilterPunc": 0,
            "ConvertNumMode": 1,
            "WordInfo": 0,
        }
        if self.settings.tencent_hotword_id:
            request_payload["HotwordId"] = self.settings.tencent_hotword_id
        if self.settings.tencent_hotword_list:
            request_payload["HotwordList"] = self.settings.tencent_hotword_list
        req = models.SentenceRecognitionRequest()
        req.from_json_string(json.dumps(request_payload))
        resp = client.SentenceRecognition(req)
        data = json.loads(resp.to_json_string())
        result = data.get("Result", "").strip()
        if not result:
            raise RuntimeError(f"Tencent ASR returned an empty transcript: {data}")
        return data

    def _normalize_transcript(self, transcript: str) -> str:
        text = transcript.strip()
        for source, target in self.settings.wake_replacements.items():
            text = text.replace(source, target)
        return text

    def _match_wake_phrase(self, transcript: str) -> tuple[bool, str, str, str]:
        normalized_text = self._normalize_transcript(transcript)
        if not self.settings.wake_phrases:
            return False, normalized_text, "", normalized_text
        for phrase in self.settings.wake_phrases:
            index = normalized_text.find(phrase)
            if index < 0:
                continue
            command_text = normalized_text[index + len(phrase):].strip(" ，,。.!！？?：:")
            return True, command_text or normalized_text, phrase, normalized_text
        return False, normalized_text, "", normalized_text

    def build_llm_prompt(self, llm_input: str, tool_definitions: list[dict[str, Any]] | None = None) -> str:
        tools = tool_definitions or []
        tool_lines = []
        for tool in tools:
            name = tool.get("name", "")
            description = tool.get("description", "")
            schema = json.dumps(tool.get("input_schema", {}), ensure_ascii=False)
            tool_lines.append(f"- {name}: {description} | input_schema={schema}")
        tools_text = "\n".join(tool_lines) if tool_lines else "- none"
        return (
            "你是家庭机器人指令解析器。\n"
            "输入内容已经经过语音识别、关键词纠偏和唤醒词剥离。\n"
            f"当前用户命令: {llm_input}\n"
            "当前可用工具列表:\n"
            f"{tools_text}\n"
            "请不要解释过程，不要补充无关内容，只返回一个 JSON 对象。\n"
            "如果能映射到工具，请返回:\n"
            "{\"intent\":\"tool_call\",\"tool\":\"工具名\",\"arguments\":{...},\"reply\":\"给用户的简短中文回复\"}\n"
            "如果暂时不能映射到工具，请返回:\n"
            "{\"intent\":\"chat\",\"reply\":\"给用户的简短中文回复\"}"
        )

    def ask_llm(self, llm_input: str, tool_definitions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if not llm_input:
            return {"enabled": False, "output": "", "prompt": "", "parsed_output": None}
        if not self.settings.openai_api_key or not self.settings.openai_model:
            return {"enabled": False, "output": "", "prompt": "", "parsed_output": None}

        base_url = self.settings.openai_base_url.rstrip("/")
        prompt = self.build_llm_prompt(llm_input, tool_definitions)
        payload = {
            "model": self.settings.openai_model,
            "temperature": self.settings.openai_temperature,
            "thinking": {"type": self.settings.openai_thinking_type},
            "messages": [
                {
                    "role": "system",
                    "content": "你是家庭机器人语音控制层。严格返回 JSON，不要输出 Markdown。",
                },
                {"role": "user", "content": prompt},
            ],
        }
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"LLM request failed: {detail or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM request failed: {exc.reason}") from exc

        output = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        return {
            "enabled": True,
            "output": output,
            "prompt": prompt,
            "parsed_output": self._parse_llm_json(output),
        }

    def process(self, audio_bytes: bytes, voice_format: str = "wav", tool_definitions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        asr_data = self.recognize(audio_bytes, voice_format=voice_format)
        transcript = asr_data.get("Result", "").strip()
        wake_phrase_matched, command_text, matched_phrase, normalized_transcript = self._match_wake_phrase(transcript)
        llm_input = command_text if wake_phrase_matched else ""
        llm_data = self.ask_llm(llm_input, tool_definitions) if wake_phrase_matched else {
            "enabled": False,
            "output": "",
            "prompt": "",
            "parsed_output": None,
        }
        return {
            "ok": True,
            "transcript": transcript,
            "normalized_transcript": normalized_transcript,
            "wake_phrases": self.settings.wake_phrases,
            "wake_phrase": matched_phrase,
            "wake_phrase_matched": wake_phrase_matched,
            "command_text": command_text,
            "llm_input": llm_input,
            "llm_enabled": llm_data["enabled"],
            "llm_prompt": llm_data["prompt"],
            "llm_output": llm_data["output"],
            "llm_parsed_output": llm_data.get("parsed_output"),
            "tencent_request_id": asr_data.get("RequestId"),
            "tencent_audio_duration_ms": asr_data.get("AudioDuration"),
            "tencent_word_size": asr_data.get("WordSize"),
            "tencent_word_list": asr_data.get("WordList"),
        }
