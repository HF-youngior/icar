from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.state import StateHub


def write_json(path: Path, value: Any) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def make_config(tmp_path: Path, *, points: list[dict[str, Any]] | None = None, routes: list[dict[str, Any]] | None = None) -> AppConfig:
    points_file = write_json(tmp_path / "points.json", points or [])
    routes_file = write_json(tmp_path / "routes.json", routes or [])
    reports_dir = tmp_path / "reports"
    captures_dir = tmp_path / "captures"
    return AppConfig(
        points_file=str(points_file),
        routes_file=str(routes_file),
        reports_dir=str(reports_dir),
        captures_dir=str(captures_dir),
    )


def make_state(tmp_path: Path, *, points: list[dict[str, Any]] | None = None, routes: list[dict[str, Any]] | None = None) -> StateHub:
    return StateHub(make_config(tmp_path, points=points, routes=routes))
