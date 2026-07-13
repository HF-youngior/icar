from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT


class VoiceInteractionStore:
    def __init__(self) -> None:
        self.data_dir = PROJECT_ROOT / "data" / "voice"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.records_path = self.data_dir / "interactions.jsonl"

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        item = {
            "interaction_id": f"voice-{uuid.uuid4().hex[:12]}",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            **record,
        }
        with self.records_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(item, ensure_ascii=False) + "\n")
        return item

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.records_path.exists():
            return []
        lines = self.records_path.read_text(encoding="utf-8").splitlines()
        records: list[dict[str, Any]] = []
        for line in reversed(lines[-max(1, limit):]):
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records
