from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("VOICE_WAKE_PHRASES", '["小比","小比小比","比格","小比格"]')
os.environ.setdefault("VOICE_WAKE_REPLACEMENTS", '["小臂=小比","小臂小臂=小比小比"]')

from app.mcp_tools import McpToolService  # noqa: E402
from app.voice import VoicePipeline  # noqa: E402


def _distance_from_text(text: str) -> float:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*米", text)
    if match:
        return float(match.group(1))
    chinese_numbers = {
        "一": 1.0,
        "二": 2.0,
        "两": 2.0,
        "三": 3.0,
        "四": 4.0,
        "五": 5.0,
    }
    for word, value in chinese_numbers.items():
        if f"{word}米" in text:
            return value
    return 1.0


def fake_llm(normalized_text: str) -> dict[str, Any]:
    if "前进" in normalized_text or "向前" in normalized_text:
        meters = _distance_from_text(normalized_text)
        parsed = {
            "intent": "tool_call",
            "intent_summary": f"向前移动{meters:g}米",
            "reply": "好的",
            "tool_calls": [
                {"name": "speak", "arguments": {"mode": "preset", "preset_key": "ok", "text": "好的"}},
                {"name": "move_distance", "arguments": {"direction": "forward", "meters": meters}},
            ],
        }
        return {
            "enabled": True,
            "output": json.dumps(parsed, ensure_ascii=False),
            "prompt": "[mock llm prompt omitted]",
            "parsed_output": parsed,
        }

    parsed = {
        "intent": "unknown",
        "intent_summary": "能力外请求",
        "reply": "我不会",
        "tool_calls": [
            {"name": "speak", "arguments": {"mode": "preset", "preset_key": "unknown", "text": "我不会"}},
        ],
    }
    return {
        "enabled": True,
        "output": json.dumps(parsed, ensure_ascii=False),
        "prompt": "[mock llm prompt omitted]",
        "parsed_output": parsed,
    }


def dry_run_tool_call(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "speak":
        mode = str(arguments.get("mode", "")).strip()
        preset_key = str(arguments.get("preset_key", "")).strip()
        prepared = McpToolService.prepared_voices.get(preset_key, {})
        text = str(prepared.get("text", "") if mode == "preset" else arguments.get("text", "")).strip()
        return {
            "ok": True,
            "dry_run": True,
            "tool": "speak",
            "mode": mode,
            "preset_key": preset_key,
            "text": text,
            "would_play_prepared_voice": mode == "preset",
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
            "duration_sec": round(meters / speed_mps, 3),
            "would_send_chassis_command": direction in {"forward", "backward"} and meters > 0,
        }

    return {
        "ok": False,
        "dry_run": True,
        "tool": tool_name,
        "error": "unsupported mock tool",
    }


def run_case(pipeline: VoicePipeline, transcript: str) -> dict[str, Any]:
    normalized = pipeline._normalize_transcript(transcript)
    wake_matched = any(phrase in normalized for phrase in pipeline.settings.wake_phrases)
    llm_data = fake_llm(normalized) if wake_matched else None
    result = pipeline.process_transcript(
        transcript,
        asr_data={
            "Result": transcript,
            "RequestId": f"mock-{abs(hash(transcript))}",
            "AudioDuration": 0,
        },
        tool_definitions=[],
        llm_data=llm_data,
    )

    tool_executions: list[dict[str, Any]] = []
    parsed = result.get("llm_parsed_output")
    if isinstance(parsed, dict):
        for call in parsed.get("tool_calls", []):
            if isinstance(call, dict):
                tool_executions.append(dry_run_tool_call(str(call.get("name", "")), call.get("arguments") or {}))

    blocked_reason = ""
    if not result["wake_phrase_matched"]:
        blocked_reason = "未唤醒状态下没有匹配唤醒词，拦截：不进入 LLM，不执行 MCP。"

    return {
        "input_asr_text": transcript,
        "state_before": "idle",
        "normalized_text": result["normalized_transcript"],
        "wake_phrase_matched": result["wake_phrase_matched"],
        "wake_phrase": result["wake_phrase"],
        "llm_called": bool(result["llm_enabled"]),
        "llm_input": result["llm_input"],
        "llm_parsed_output": result["llm_parsed_output"],
        "tool_executions": tool_executions,
        "blocked_reason": blocked_reason,
    }


def main() -> int:
    pipeline = VoicePipeline()
    cases = ["小比小比，前进两米", "小臂小臂，前进两米", "前进两米"]
    report = [run_case(pipeline, item) for item in cases]

    print("Voice chain mock report")
    print("=" * 80)
    for index, item in enumerate(report, start=1):
        print(f"\nCASE {index}: {item['input_asr_text']}")
        print(f"state_before: {item['state_before']}")
        print(f"normalized_text: {item['normalized_text']}")
        print(f"wake_phrase_matched: {item['wake_phrase_matched']} ({item['wake_phrase'] or '-'})")
        print(f"llm_called: {item['llm_called']}")
        if item["llm_input"]:
            print(f"llm_input: {item['llm_input']}")
        if item["llm_parsed_output"]:
            print("llm_parsed_output:")
            print(json.dumps(item["llm_parsed_output"], ensure_ascii=False, indent=2))
        if item["tool_executions"]:
            print("mcp_tool_executions:")
            print(json.dumps(item["tool_executions"], ensure_ascii=False, indent=2))
        if item["blocked_reason"]:
            print(f"blocked_reason: {item['blocked_reason']}")

    print("\nJSON summary")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
