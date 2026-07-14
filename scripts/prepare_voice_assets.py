from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


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

from app.config import load_config  # noqa: E402
from app.car_runtime import CarRuntimeRecovery  # noqa: E402
from app.mcp_tools import McpToolService  # noqa: E402
from app.prepared_voice_assets import PreparedVoiceAssetService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate local prepared voice audio files with Tencent Cloud TTS.")
    parser.add_argument("--overwrite", action="store_true", help="Regenerate files even when they already exist.")
    args = parser.parse_args()

    runtime = CarRuntimeRecovery(load_config())
    service = PreparedVoiceAssetService(runtime, McpToolService.prepared_voices)
    result = service.generate_local_assets(overwrite=args.overwrite)
    print(json.dumps(
        {
            "ok": result["ok"],
            "local_dir": result["local_dir"],
            "generated": result["generated"],
            "skipped": result["skipped"],
            "errors": result["errors"],
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
