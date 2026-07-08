from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YOLOv5 inference wrapper for Jetson/PC.")
    parser.add_argument("--yolov5-dir", required=True, help="Path to YOLOv5-7.0 source directory.")
    parser.add_argument("--weights", required=True, help="Model weights path, for example best.pt.")
    parser.add_argument("--source", default="0", help="Camera index, image, video or stream URL.")
    parser.add_argument("--img", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--project", default="runs/detect-home")
    parser.add_argument("--name", default="homebot")
    parser.add_argument("--save-txt", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    yolov5_dir = Path(args.yolov5_dir).resolve()
    detect_py = yolov5_dir / "detect.py"
    if not detect_py.exists():
        raise SystemExit(f"detect.py not found: {detect_py}")

    command = [
        sys.executable,
        str(detect_py),
        "--weights",
        str(Path(args.weights).resolve()),
        "--source",
        args.source,
        "--img",
        str(args.img),
        "--conf",
        str(args.conf),
        "--project",
        args.project,
        "--name",
        args.name,
    ]
    if args.save_txt:
        command.append("--save-txt")
    print("Running:", " ".join(command))
    subprocess.run(command, cwd=yolov5_dir, check=True)

    result_dir = yolov5_dir / args.project / args.name
    print(json.dumps({"ok": True, "result_dir": str(result_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

