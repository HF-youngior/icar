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
By default, the script now loads the maintained test set from [voice-test-cases.json](C:/Users/abc/Desktop/projects/icar/docs/voice-test-cases.json).

Single custom input:

```powershell
$env:PYTHONIOENCODING='utf-8'; python scripts\mock_voice_deepseek_chain.py "小比小比，前进两米"
```

Multiple inputs:

```powershell
$env:PYTHONIOENCODING='utf-8'; python scripts\mock_voice_deepseek_chain.py "小比小比，前进两米" "小臂小臂，前进两米" "前进两米"
```

JSON array input:

```powershell
$env:PYTHONIOENCODING='utf-8'; python scripts\mock_voice_deepseek_chain.py --inputs-json "[\"小比小比，前进两米\",\"小臂小臂，前进两米\",\"前进两米\"]"
```

Recommended on PowerShell: run from the maintained test-case file instead of inline JSON:

```powershell
$env:PYTHONIOENCODING='utf-8'; python scripts\mock_voice_deepseek_chain.py --inputs-file docs\voice-test-cases.json
```

Output is intentionally simplified:

- The script now prints one line per test case:
  `[mock腾讯云输入: ..., deepseek输出: ...]`
- If the backend blocks the request before DeepSeek, the second field becomes the block reason.
- If the LLM request fails, the second field becomes the LLM error text.

Context isolation:

- Each test utterance is sent as its own fresh `chat/completions` request.
- No prior user utterances are carried into the next case.
- Reusing the same API key does not create shared conversation memory here.

Expected behavior:

- `小比小比，前进两米`: should call DeepSeek and produce a voice reply plus `move_distance`.
- `小臂小臂，前进两米`: should normalize to `小比小比，前进两米`, then behave like the first case.
- `前进两米`: should be blocked in idle state, with no DeepSeek call and no MCP tool execution.
