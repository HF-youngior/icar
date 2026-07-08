from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / ".vendor"))
sys.path.insert(0, str(ROOT / "backend"))

from app.config import load_config  # noqa: E402
from app.database import DatabaseStore  # noqa: E402


def main() -> None:
    config = load_config()
    if not config.database.enabled:
        raise SystemExit("Database is disabled. Set ICAR_DB_HOST, ICAR_DB_USER, ICAR_DB_PASSWORD and ICAR_DB_NAME.")
    store = DatabaseStore(config.database)
    store.init_schema()
    print(json.dumps(store.health(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

