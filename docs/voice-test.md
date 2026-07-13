# Voice Chain Test Commands

## 1. Local mock: Tencent ASR + LLM + MCP dry run

```powershell
$env:PYTHONIOENCODING='utf-8'; python scripts\mock_voice_chain.py
```

This command does not call Tencent Cloud, DeepSeek, TTS, or the real car. It injects three mocked ASR texts and uses a fake LLM response to verify wake-word matching, homophone replacement, idle-state blocking, and MCP argument calculation.

Current test inputs:

- `小比小比，前进两米`
- `小臂小臂，前进两米`
- `前进两米`

## 2. Mock Tencent ASR text + real DeepSeek + MCP dry run

```powershell
$env:PYTHONIOENCODING='utf-8'; python scripts\mock_voice_deepseek_chain.py
```

This command still does not call Tencent Cloud or move the car, but it does call the configured DeepSeek/OpenAI-compatible chat API from `.env`. It checks whether the real model returns valid JSON, whether `intent_summary` and `tool_calls` are usable, and what MCP tools would run in dry-run mode.

Before running it, make sure `.env` contains a non-empty `OPENAI_API_KEY`.

Expected behavior:

- `小比小比，前进两米`: should call DeepSeek and produce a voice reply plus `move_distance`.
- `小臂小臂，前进两米`: should normalize to `小比小比，前进两米`, then behave like the first case.
- `前进两米`: should be blocked in idle state, with no DeepSeek call and no MCP tool execution.
