from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
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


load_dotenv(ROOT / ".env")
os.environ.setdefault("VOICE_WAKE_PHRASES", '["小比","小比小比","比格","小比格"]')
os.environ.setdefault("VOICE_WAKE_REPLACEMENTS", '["小臂=小比","小臂小臂=小比小比"]')

from app.mcp_tools import McpToolService  # noqa: E402
from app.voice import VoicePipeline  # noqa: E402


def dry_run_tool_call(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "speak":
        mode = str(arguments.get("mode", "")).strip()
        preset_key = str(arguments.get("preset_key", "")).strip()
        text = str(arguments.get("text", "")).strip()
        prepared = McpToolService.prepared_voices.get(preset_key, {})
        return {
            "ok": True,
            "dry_run": True,
            "tool": "speak",
            "mode": mode,
            "preset_key": preset_key,
            "text": text or prepared.get("text", ""),
            "would_play_prepared_voice": mode == "preset",
            "would_submit_tts": mode == "tts",
        }

    if tool_name == "move_distance":
        direction = str(arguments.get("direction", "")).strip()
        meters = float(arguments.get("meters", 0))
        speed_mps = McpToolService.fixed_speed_mps
        return {
            "ok": True,
            "dry_run": True,
            "tool": "move_distance",
            "direction": direction,
            "meters": meters,
            "speed_mps": speed_mps,
            "duration_sec": round(meters / speed_mps, 3) if meters else 0,
            "would_send_chassis_command": direction in {"forward", "backward"} and meters > 0,
        }

    return {
        "ok": False,
        "dry_run": True,
        "tool": tool_name,
        "error": "unsupported mock tool",
    }


def dry_run_tools(parsed_output: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(parsed_output, dict):
        return []

    calls: list[dict[str, Any]] = []
    raw_calls = parsed_output.get("tool_calls")
    if isinstance(raw_calls, list):
        calls = [item for item in raw_calls if isinstance(item, dict)]
    elif parsed_output.get("intent") == "tool_call":
        calls = [
            {
                "name": parsed_output.get("tool", ""),
                "arguments": parsed_output.get("arguments", {}),
            }
        ]

    results: list[dict[str, Any]] = []
    for call in calls:
        tool_name = str(call.get("name") or call.get("tool") or "").strip()
        arguments = call.get("arguments") or {}
        if tool_name:
            results.append(dry_run_tool_call(tool_name, arguments))
    return results


def run_case(pipeline: VoicePipeline, transcript: str) -> dict[str, Any]:
    result = pipeline.process_transcript(
        transcript,
        asr_data={
            "Result": transcript,
            "RequestId": f"mock-tencent-{abs(hash(transcript))}",
            "AudioDuration": 0,
        },
        tool_definitions=McpToolService(None, None, None).tool_definitions(),  # type: ignore[arg-type]
    )
    tool_executions = dry_run_tools(result.get("llm_parsed_output"))
    blocked_reason = ""
    if not result["wake_phrase_matched"]:
        blocked_reason = "未唤醒状态下没有匹配唤醒词，拦截：不调用 DeepSeek，不执行 MCP。"

    return {
        "input_asr_text": transcript,
        "state_before": "idle",
        "normalized_text": result["normalized_transcript"],
        "wake_phrase_matched": result["wake_phrase_matched"],
        "wake_phrase": result["wake_phrase"],
        "deepseek_called": bool(result["llm_enabled"]),
        "deepseek_input": result["llm_input"],
        "deepseek_raw_output": result["llm_output"],
        "deepseek_parsed_output": result["llm_parsed_output"],
        "mcp_dry_run_executions": tool_executions,
        "blocked_reason": blocked_reason,
    }


def main() -> int:
    pipeline = VoicePipeline()
    if not pipeline.settings.openai_api_key:
        print("OPENAI_API_KEY is missing. Fill .env before running the DeepSeek mock chain.")
        return 2

    cases = ["小比小比，前进两米", "小臂小臂，前进两米", "前进两米"]
    report = [run_case(pipeline, item) for item in cases]

    print("Voice chain mock Tencent + real DeepSeek report")
    print("=" * 80)
    for index, item in enumerate(report, start=1):
        print(f"\nCASE {index}: {item['input_asr_text']}")
        print(f"state_before: {item['state_before']}")
        print(f"normalized_text: {item['normalized_text']}")
        print(f"wake_phrase_matched: {item['wake_phrase_matched']} ({item['wake_phrase'] or '-'})")
        print(f"deepseek_called: {item['deepseek_called']}")
        if item["deepseek_input"]:
            print(f"deepseek_input: {item['deepseek_input']}")
        if item["deepseek_raw_output"]:
            print("deepseek_raw_output:")
            print(item["deepseek_raw_output"])
        if item["deepseek_parsed_output"]:
            print("deepseek_parsed_output:")
            print(json.dumps(item["deepseek_parsed_output"], ensure_ascii=False, indent=2))
        if item["mcp_dry_run_executions"]:
            print("mcp_dry_run_executions:")
            print(json.dumps(item["mcp_dry_run_executions"], ensure_ascii=False, indent=2))
        if item["blocked_reason"]:
            print(f"blocked_reason: {item['blocked_reason']}")

    print("\nJSON summary")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
