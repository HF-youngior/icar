from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YOLOv5 training wrapper for the home robot project.")
    parser.add_argument("--yolov5-dir", required=True, help="Path to YOLOv5-7.0 source directory.")
    parser.add_argument("--data", default="vision/yolov5_home.yaml", help="Dataset yaml path.")
    parser.add_argument("--weights", default="yolov5s.pt", help="Initial weights, for example yolov5s.pt.")
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--img", type=int, default=640)
    parser.add_argument("--project", default="runs/train-home")
    parser.add_argument("--name", default="homebot")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    yolov5_dir = Path(args.yolov5_dir).resolve()
    train_py = yolov5_dir / "train.py"
    if not train_py.exists():
        raise SystemExit(f"train.py not found: {train_py}")

    command = [
        sys.executable,
        str(train_py),
        "--img",
        str(args.img),
        "--batch",
        str(args.batch_size),
        "--epochs",
        str(args.epochs),
        "--data",
        str(Path(args.data).resolve()),
        "--weights",
        args.weights,
        "--project",
        args.project,
        "--name",
        args.name,
    ]
    print("Running:", " ".join(command))
    subprocess.run(command, cwd=yolov5_dir, check=True)


if __name__ == "__main__":
    main()

