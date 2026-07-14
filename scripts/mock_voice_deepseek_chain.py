from __future__ import annotations

import argparse
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
        prepared = McpToolService.prepared_voices.get(preset_key, {})
        text = str(prepared.get("text", "") if mode == "preset" else arguments.get("text", "")).strip()
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

    if tool_name == "turn_degrees":
        direction = str(arguments.get("direction", "")).strip()
        degrees = int(arguments.get("degrees", 0))
        pulse_count = degrees // McpToolService.turn_degrees_per_pulse if degrees else 0
        return {
            "ok": True,
            "dry_run": True,
            "tool": "turn_degrees",
            "direction": direction,
            "degrees": degrees,
            "degrees_per_pulse": McpToolService.turn_degrees_per_pulse,
            "pulse_count": pulse_count,
            "speed": McpToolService.fixed_turn_speed,
            "pulse_ms": McpToolService.turn_pulse_ms,
            "interval_ms": McpToolService.turn_interval_ms,
            "would_send_chassis_command": direction in {"left", "right"} and degrees in {90, 180, 270, 360},
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


def _extract_cases_from_json_payload(payload: Any) -> list[str]:
    if isinstance(payload, list):
        return [str(item).strip() for item in payload if str(item).strip()]
    if isinstance(payload, dict):
        cases: list[str] = []
        for value in payload.values():
            if isinstance(value, list):
                cases.extend(str(item).strip() for item in value if str(item).strip())
            elif isinstance(value, dict):
                cases.extend(_extract_cases_from_json_payload(value))
        return cases
    return []


def load_cases_from_file(path_str: str) -> list[str]:
    path = Path(path_str)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise SystemExit(f"--inputs-file not found: {path}")

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []

    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--inputs-file JSON parse failed: {exc}") from exc
        cases = _extract_cases_from_json_payload(payload)
        if not cases:
            raise SystemExit("--inputs-file JSON did not contain any test utterances.")
        return cases

    cases = []
    for line in text.splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#") or candidate.startswith("- "):
            continue
        cases.append(candidate)
    return cases


def parse_cases(argv: list[str]) -> list[str]:
    parser = argparse.ArgumentParser(
        description="Mock Tencent ASR text -> real DeepSeek -> MCP dry-run reporter."
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="One or more mocked Tencent ASR texts.",
    )
    parser.add_argument(
        "--inputs-json",
        dest="inputs_json",
        default="",
        help='JSON array of mocked Tencent ASR texts, e.g. ["小比小比，前进两米","前进两米"]',
    )
    parser.add_argument(
        "--inputs-file",
        dest="inputs_file",
        default="",
        help="Path to a UTF-8 test-case file. Supports JSON or plain text.",
    )
    args = parser.parse_args(argv)

    if args.inputs_file:
        cases = load_cases_from_file(args.inputs_file)
        if cases:
            return cases

    if args.inputs_json:
        try:
            loaded = json.loads(args.inputs_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--inputs-json is not valid JSON: {exc}") from exc
        cases = _extract_cases_from_json_payload(loaded)
        if cases:
            return cases
        raise SystemExit("--inputs-json must contain at least one test utterance.")

    cases = [item.strip() for item in args.inputs if item.strip()]
    if cases:
        return cases

    return load_cases_from_file("docs/voice-test-cases.json")


def run_case(transcript: str) -> dict[str, Any]:
    pipeline = VoicePipeline()
    try:
        result = pipeline.process_transcript(
            transcript,
            asr_data={
                "Result": transcript,
                "RequestId": f"mock-tencent-{abs(hash(transcript))}",
                "AudioDuration": 0,
            },
            tool_definitions=McpToolService(None, None, None, None).tool_definitions(),  # type: ignore[arg-type]
        )
    except Exception as exc:
        return {
            "mock_tencent_input": transcript,
            "normalized_text": transcript,
            "deepseek_called": False,
            "deepseek_output": "",
            "mcp_dry_run_executions": [],
            "blocked_reason": "",
            "llm_error": str(exc),
        }
    blocked_reason = ""
    if not result["wake_phrase_matched"]:
        blocked_reason = "未唤醒状态下没有匹配唤醒词，拦截：不调用 DeepSeek，不执行 MCP。"

    parsed_output = result.get("llm_parsed_output")
    tool_executions = dry_run_tools(parsed_output)
    return {
        "mock_tencent_input": transcript,
        "normalized_text": result["normalized_transcript"],
        "deepseek_called": bool(result["llm_enabled"]),
        "deepseek_output": parsed_output if isinstance(parsed_output, dict) else result.get("llm_output", ""),
        "mcp_dry_run_executions": tool_executions,
        "blocked_reason": blocked_reason,
        "llm_error": "",
    }


def summarize_reply(item: dict[str, Any]) -> str:
    if item.get("llm_error"):
        return f"llm_error: {item['llm_error']}"
    if item.get("blocked_reason"):
        return item["blocked_reason"]

    deepseek_output = item.get("deepseek_output")
    if isinstance(deepseek_output, dict):
        reply = str(deepseek_output.get("reply", "")).strip()
        if reply:
            return reply
        intent_summary = str(deepseek_output.get("intent_summary", "")).strip()
        if intent_summary:
            return f"(no reply) {intent_summary}"
    return str(deepseek_output or "").strip() or "(empty)"


def main() -> int:
    settings_probe = VoicePipeline()
    if not settings_probe.settings.openai_api_key:
        print("OPENAI_API_KEY is missing. Fill .env before running the DeepSeek mock chain.")
        return 2

    cases = parse_cases(sys.argv[1:])
    for transcript in cases:
        item = run_case(transcript)
        reply = summarize_reply(item).replace("\r", " ").replace("\n", " ").strip()
        print(f"[mock腾讯云输入: {item['mock_tencent_input']}, deepseek输出: {reply}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
