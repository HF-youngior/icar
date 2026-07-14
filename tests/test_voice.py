from __future__ import annotations

import unittest
from typing import Any

from tests import BACKEND  # noqa: F401

from app.voice import VoicePipeline


class EmptyAsrVoicePipeline(VoicePipeline):
    def recognize(self, audio_bytes: bytes, voice_format: str = "wav") -> dict[str, Any]:
        return {
            "Result": "",
            "AudioDuration": 2730,
            "WordSize": 0,
            "WordList": None,
            "RequestId": "mock-empty-asr",
        }

    def ask_llm(self, llm_input: str, tool_definitions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        raise AssertionError("LLM should not be called when ASR transcript is empty")


class VoicePipelineTest(unittest.TestCase):
    def test_empty_asr_result_is_not_treated_as_runtime_error(self) -> None:
        pipeline = EmptyAsrVoicePipeline()

        result = pipeline.process(b"fake wav bytes")

        self.assertTrue(result["ok"])
        self.assertTrue(result["asr_empty"])
        self.assertEqual(result["transcript"], "")
        self.assertEqual(result["normalized_transcript"], "")
        self.assertFalse(result["wake_phrase_matched"])
        self.assertFalse(result["llm_enabled"])
        self.assertEqual(result["llm_output"], "")
        self.assertIsNone(result["llm_parsed_output"])
        self.assertEqual(result["tencent_request_id"], "mock-empty-asr")
        self.assertEqual(result["tencent_word_size"], 0)

    def test_empty_transcript_does_not_enter_llm_path(self) -> None:
        pipeline = EmptyAsrVoicePipeline()

        result = pipeline.process_transcript(
            "",
            asr_data={"Result": "", "RequestId": "manual-empty"},
        )

        self.assertTrue(result["asr_empty"])
        self.assertEqual(result["llm_input"], "")
        self.assertFalse(result["llm_enabled"])


if __name__ == "__main__":
    unittest.main()
