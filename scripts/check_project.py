from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> None:
    json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    required = [
        ROOT / "README.md",
        ROOT / "backend" / "requirements.txt",
        ROOT / "backend" / "app" / "main.py",
        ROOT / "frontend" / "index.html",
        ROOT / "frontend" / "assets" / "css" / "styles.css",
        ROOT / "frontend" / "assets" / "js" / "app.js",
        ROOT / "frontend" / "control.html",
        ROOT / "frontend" / "navigation.html",
        ROOT / "frontend" / "vision.html",
        ROOT / "frontend" / "alarms.html",
        ROOT / "frontend" / "reports.html",
        ROOT / "config" / "app.example.json",
        ROOT / "config" / "points.json",
        ROOT / "config" / "routes.json",
        ROOT / "docs" / "database.md",
        ROOT / "docs" / "car-connection.md",
        ROOT / "scripts" / "db_check.py",
        ROOT / "vision" / "train_yolov5.py",
        ROOT / "vision" / "infer_yolov5.py",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("Missing files:\n" + "\n".join(missing))
    for name in ["app.example.json", "points.json", "routes.json"]:
        load_json(ROOT / "config" / name)
    print("Project check passed.")


if __name__ == "__main__":
    main()
