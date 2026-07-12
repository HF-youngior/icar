#!/usr/bin/env python3
from __future__ import annotations

import argparse
import signal
import socketserver
import threading
from dataclasses import dataclass

from Rosmaster_Lib import Rosmaster


@dataclass
class BridgeConfig:
    host: str
    port: int
    speed: int
    debug: bool


class RosmasterController:
    def __init__(self, speed: int, debug: bool = False) -> None:
        self.speed = speed
        self.debug = debug
        self.lock = threading.Lock()
        self.bot = Rosmaster(debug=debug)
        self.bot.create_receive_threading()

    def apply_frame(self, frame: str) -> str | None:
        direction_code = self.decode_frame(frame)
        if direction_code is None:
            return None

        # Web frame codes follow the existing Harmony/TCP adapter.
        # Rosmaster's local app uses run states 5=right turn and 6=left turn.
        run_state_by_code = {
            "00": 7,  # stop
            "01": 1,  # forward
            "02": 2,  # backward
            "03": 4,  # left shift
            "04": 3,  # right shift
            "05": 6,  # left turn
            "06": 5,  # right turn
            "07": 7,  # emergency stop
        }
        run_state = run_state_by_code.get(direction_code)
        if run_state is None:
            return None

        with self.lock:
            if run_state == 7:
                self._stop()
            else:
                self.bot.set_car_run(run_state, self.speed, adjust=False)
        return self.describe(direction_code)

    def _stop(self) -> None:
        try:
            self.bot.set_car_motion(0, 0, 0)
        except Exception:
            pass
        self.bot.set_car_run(7, 0, adjust=False)

    def stop(self) -> None:
        with self.lock:
            self._stop()

    def decode_frame(self, frame: str) -> str | None:
        if len(frame) < 10 or not frame.startswith("$") or not frame.endswith("#"):
            return None
        body = frame[1:-1]
        if len(body) % 2 != 0 or len(body) < 8:
            return None
        payload = body[:-2]
        checksum = body[-2:].upper()
        if self.checksum(payload) != checksum:
            if self.debug:
                print(f"bad checksum: {frame}, expected {self.checksum(payload)}", flush=True)
            return None
        command = payload[2:4]
        if command != "15":
            return None
        return payload[6:8].upper()

    def checksum(self, payload: str) -> str:
        total = 0
        for index in range(0, len(payload), 2):
            total = (total + int(payload[index:index + 2], 16)) % 256
        return f"{total:02X}"

    def describe(self, direction_code: str) -> str:
        return {
            "00": "stop",
            "01": "forward",
            "02": "backward",
            "03": "left_shift",
            "04": "right_shift",
            "05": "left",
            "06": "right",
            "07": "emergency_stop",
        }.get(direction_code, "unknown")


class ThreadedTcpServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def extract_frames(text: str) -> list[str]:
    frames: list[str] = []
    start = text.find("$")
    while start >= 0:
        end = text.find("#", start)
        if end < 0:
            break
        frames.append(text[start:end + 1])
        start = text.find("$", end + 1)
    return frames


def build_handler(controller: RosmasterController):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            peer = self.client_address
            while True:
                data = self.request.recv(1024)
                if not data:
                    break
                text = data.decode("utf-8", errors="ignore")
                for frame in extract_frames(text):
                    direction = controller.apply_frame(frame)
                    if direction is None:
                        self.request.sendall(f"ERR ignored {frame}\n".encode("utf-8"))
                        continue
                    print(f"command from {peer}: {direction} ({frame})", flush=True)
                    self.request.sendall(f"OK {direction}\n".encode("utf-8"))

    return Handler


def parse_args() -> BridgeConfig:
    parser = argparse.ArgumentParser(description="Bridge Web TCP control frames to Rosmaster_Lib.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=6001)
    parser.add_argument("--speed", type=int, default=50)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    return BridgeConfig(
        host=args.host,
        port=args.port,
        speed=max(0, min(100, args.speed)),
        debug=args.debug,
    )


def main() -> None:
    config = parse_args()
    controller = RosmasterController(speed=config.speed, debug=config.debug)
    server = ThreadedTcpServer((config.host, config.port), build_handler(controller))

    def shutdown(_signum, _frame) -> None:
        controller.stop()
        server.shutdown()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    print(
        f"Rosmaster TCP bridge listening on {config.host}:{config.port}, speed={config.speed}",
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        controller.stop()
        server.server_close()


if __name__ == "__main__":
    main()
