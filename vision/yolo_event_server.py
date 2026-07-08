from __future__ import annotations

import argparse
import json
import socket
from datetime import datetime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minimal YOLO event TCP server placeholder.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=12345)
    return parser.parse_args()


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    args = parse_args()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((args.host, args.port))
        server.listen(1)
        print(f"YOLO event server listening on {args.host}:{args.port}")
        while True:
            conn, addr = server.accept()
            with conn:
                payload = {
                    "type": "vision_event",
                    "payload": {
                        "label": "person",
                        "label_zh": "人员",
                        "confidence": 0.86,
                        "bbox": [120, 80, 260, 360],
                        "source": "tcp-placeholder",
                        "timestamp": now_text(),
                    },
                }
                conn.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
                print(f"sent sample event to {addr}")


if __name__ == "__main__":
    main()

