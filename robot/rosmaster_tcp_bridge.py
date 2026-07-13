#!/usr/bin/env python3
from __future__ import annotations

import argparse
import signal
import socketserver
import threading
import time
from dataclasses import dataclass

from Rosmaster_Lib import Rosmaster


@dataclass
class BridgeConfig:
    host: str
    port: int
    speed: int
    debug: bool
    pulse_timeout_sec: float


class RosmasterController:
    def __init__(self, speed: int, debug: bool = False, pulse_timeout_sec: float = 0.45) -> None:
        self.speed = speed
        self.debug = debug
        self.pulse_timeout_sec = max(0.1, pulse_timeout_sec)
        self.motion_deadline: float | None = None
        self.closed = False
        self.lock = threading.Lock()
        self.bot = Rosmaster(debug=debug)
        self.bot.create_receive_threading()
        self.watchdog = threading.Thread(target=self._watchdog_loop, daemon=True)
        self.watchdog.start()

    def apply_frame(self, frame: str) -> str | None:
        payload = self.parse_frame(frame)
        if payload is None or len(payload) < 3:
            return None
        command = payload[1]

        if command == 0x15 and len(payload) >= 4 and payload[2] == 0x04:
            return self.apply_movement(f"{payload[3]:02X}")

        if command == 0x16 and len(payload) >= 5:
            return self.apply_speed(max(payload[3], payload[4]))

        if command == 0x63:
            return self.apply_follow_line(True)

        if command == 0x64:
            return self.apply_follow_line(False)

        if command == 0x13 and len(payload) >= 5:
            duration_ms = payload[4] * 10 if payload[3] else 0
            return self.apply_buzzer(duration_ms)

        if command == 0x05 and len(payload) >= 7 and payload[3] in {0, 1} and payload[4] in {0, 1}:
            duration_ms = payload[5] | (payload[6] << 8)
            return self.apply_headlights(bool(payload[3]), bool(payload[4]), duration_ms)

        if command in {0x05, 0x30} and len(payload) >= 7:
            return self.apply_light(payload[3], payload[4], payload[5], payload[6])

        if command in {0x06, 0x31} and len(payload) >= 5:
            return self.apply_light_effect(payload[3], payload[4])

        return None

    def apply_speed(self, speed: int) -> str:
        with self.lock:
            self.speed = max(0, min(100, speed))
        return f"speed_{self.speed}"

    def apply_movement(self, direction_code: str) -> str | None:
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
                self.motion_deadline = None
                self._stop()
            else:
                self.bot.set_car_run(run_state, self.speed, adjust=False)
                self.motion_deadline = time.monotonic() + self.pulse_timeout_sec
        return self.describe(direction_code)

    def apply_follow_line(self, enabled: bool) -> str:
        flag = 1 if enabled else 0
        with self.lock:
            called = self._call_optional_with_args(
                ["set_follow_line", "set_line_tracking", "set_car_trace", "set_trace", "set_tracking"],
                [(flag,), (enabled,)],
            )
            if not called and not enabled:
                self._stop()
        return f"follow_line_{'on' if enabled else 'off'}"

    def apply_buzzer(self, duration_ms: int) -> str:
        with self.lock:
            self._call_optional_with_args(
                ["set_beep", "set_buzzer", "set_beeper"],
                [(duration_ms,), (duration_ms > 0, duration_ms)],
            )
        return f"buzzer_{duration_ms}ms"

    def apply_light(self, led_id: int, red: int, green: int, blue: int) -> str:
        enabled = any((red, green, blue))
        with self.lock:
            called = self._call_optional_with_args(
                [
                    "set_colorful_lamps",
                    "set_colorful_lamp",
                    "set_rgb_lamp",
                    "set_rgb",
                    "set_led",
                    "set_light",
                    "set_lamp",
                    "set_car_light",
                    "set_car_lights",
                    "set_headlight",
                    "set_headlights",
                ],
                [
                    (led_id, red, green, blue),
                    (red, green, blue),
                    (led_id, enabled),
                    (enabled,),
                    (1 if enabled else 0,),
                ],
            )
            if not called:
                self._apply_discrete_lights(enabled)
        return f"light_{led_id}_{red}_{green}_{blue}"

    def apply_light_effect(self, effect: int, speed: int) -> str:
        with self.lock:
            self._call_optional_with_args(
                ["set_colorful_effect", "set_rgb_effect", "set_light_effect"],
                [(effect, speed, 255), (effect, speed), (effect,)],
            )
        return f"light_effect_{effect}_{speed}"

    def apply_headlights(self, left_enabled: bool, right_enabled: bool, duration_ms: int = 0) -> str:
        enabled = left_enabled or right_enabled
        with self.lock:
            called = False
            for side, side_enabled in (("left", left_enabled), ("right", right_enabled)):
                called = self._apply_side_light(side, side_enabled) or called
            if not called:
                self._apply_discrete_lights(enabled)
            self._try_raw_protocol_frame(0x05, [
                1 if left_enabled else 0,
                1 if right_enabled else 0,
                duration_ms & 0xFF,
                (duration_ms >> 8) & 0xFF,
            ])
        return f"headlights_left_{int(left_enabled)}_right_{int(right_enabled)}_{duration_ms}ms"

    def _call_optional_with_args(self, names, arg_sets) -> bool:
        for name in names:
            method = getattr(self.bot, name, None)
            if not callable(method):
                continue
            for args in arg_sets:
                try:
                    method(*args)
                    return True
                except TypeError:
                    continue
                except Exception as exc:
                    if self.debug:
                        print(f"{name}{args} failed: {exc}", flush=True)
                    return False
        return False

    def _apply_discrete_lights(self, enabled: bool) -> bool:
        called = False
        if enabled:
            no_arg_names = [
                "set_on_left_light",
                "set_on_right_light",
                "left_light_on",
                "right_light_on",
                "turn_on_left_light",
                "turn_on_right_light",
            ]
        else:
            no_arg_names = [
                "set_off_left_light",
                "set_off_right_light",
                "left_light_off",
                "right_light_off",
                "turn_off_left_light",
                "turn_off_right_light",
            ]
        for name in no_arg_names:
            method = getattr(self.bot, name, None)
            if not callable(method):
                continue
            try:
                method()
                called = True
            except Exception as exc:
                if self.debug:
                    print(f"{name}() failed: {exc}", flush=True)
        called = self._call_optional_with_args(
            [
                "set_left_light",
                "set_right_light",
                "set_front_light",
                "set_rear_light",
                "set_head_light",
                "set_tail_light",
            ],
            [(enabled,), (1 if enabled else 0,)],
        ) or called
        return called

    def _apply_side_light(self, side: str, enabled: bool) -> bool:
        if side not in {"left", "right"}:
            return False
        if enabled:
            no_arg_names = [
                f"set_on_{side}_light",
                f"{side}_light_on",
                f"turn_on_{side}_light",
            ]
        else:
            no_arg_names = [
                f"set_off_{side}_light",
                f"{side}_light_off",
                f"turn_off_{side}_light",
            ]
        called = self._call_optional_with_args(no_arg_names, ((),))
        called = self._call_optional_with_args(
            [f"set_{side}_light", f"set_{side}_headlight"],
            ((enabled,), (1 if enabled else 0,)),
        ) or called
        return called

    def _try_raw_protocol_frame(self, func: int, params: list[int]) -> bool:
        length = len(params) + 3
        body = [length, func] + [max(0, min(255, int(value))) for value in params]
        checksum = sum(body) & 0xFF
        frame = bytes([0xFF, 0xFC] + body + [checksum])
        for name in ("send_data", "send_cmd", "send_command", "uart_send", "serial_write", "_write_data", "write_data"):
            method = getattr(self.bot, name, None)
            if not callable(method):
                continue
            for args in ((frame,), (list(frame),), (bytearray(frame),)):
                try:
                    method(*args)
                    return True
                except TypeError:
                    continue
                except Exception as exc:
                    if self.debug:
                        print(f"{name}(raw light frame) failed: {exc}", flush=True)
                    break
        for attr in ("ser", "serial", "uart", "_serial", "_Rosmaster__ser"):
            stream = getattr(self.bot, attr, None)
            writer = getattr(stream, "write", None)
            if not callable(writer):
                continue
            try:
                writer(frame)
                return True
            except Exception as exc:
                if self.debug:
                    print(f"{attr}.write(raw light frame) failed: {exc}", flush=True)
        return False

    def _stop(self) -> None:
        try:
            self.bot.set_car_motion(0, 0, 0)
        except Exception:
            pass
        self.bot.set_car_run(7, 0, adjust=False)

    def stop(self) -> None:
        with self.lock:
            self.motion_deadline = None
            self._stop()

    def shutdown(self) -> None:
        self.closed = True
        self.stop()

    def _watchdog_loop(self) -> None:
        while not self.closed:
            time.sleep(0.05)
            with self.lock:
                if self.motion_deadline is None or time.monotonic() < self.motion_deadline:
                    continue
                self.motion_deadline = None
                if self.debug:
                    print("motion watchdog timeout: stop", flush=True)
                self._stop()

    def parse_frame(self, frame: str) -> list[int] | None:
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
        return [int(payload[index:index + 2], 16) for index in range(0, len(payload), 2)]

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
    parser.add_argument("--pulse-timeout-sec", type=float, default=0.45)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    return BridgeConfig(
        host=args.host,
        port=args.port,
        speed=max(0, min(100, args.speed)),
        debug=args.debug,
        pulse_timeout_sec=args.pulse_timeout_sec,
    )


def main() -> None:
    config = parse_args()
    controller = RosmasterController(
        speed=config.speed,
        debug=config.debug,
        pulse_timeout_sec=config.pulse_timeout_sec,
    )
    server = ThreadedTcpServer((config.host, config.port), build_handler(controller))

    def shutdown(_signum, _frame) -> None:
        controller.shutdown()
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
        controller.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
