#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import os
import socket
import time
from dataclasses import dataclass

try:
    import termios
except ModuleNotFoundError:
    termios = None


BAUD_RATES = {}
if termios is not None:
    BAUD_RATES = {
        9600: termios.B9600,
        19200: termios.B19200,
        38400: termios.B38400,
        57600: termios.B57600,
        115200: termios.B115200,
        230400: termios.B230400,
        460800: termios.B460800,
        921600: termios.B921600,
    }


@dataclass
class BridgeConfig:
    host: str
    port: int
    serial: str | None
    baud: int
    dry_run: bool


def find_serial_device() -> str | None:
    patterns = [
        "/dev/ttyUSB*",
        "/dev/ttyACM*",
        "/dev/ttyTHS*",
        "/dev/ttyS*",
    ]
    for pattern in patterns:
        for device in sorted(glob.glob(pattern)):
            if device not in {"/dev/ttyS0"}:
                return device
    return None


def open_serial(device: str, baud: int) -> int:
    if termios is None:
        raise RuntimeError("termios is only available on Linux; run this script on the Jetson car")
    if baud not in BAUD_RATES:
        raise ValueError(f"unsupported baud rate: {baud}")
    fd = os.open(device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    attrs = termios.tcgetattr(fd)
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] = termios.CLOCAL | termios.CREAD | termios.CS8
    attrs[3] = 0
    attrs[4] = BAUD_RATES[baud]
    attrs[5] = BAUD_RATES[baud]
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    return fd


def extract_frames(data: bytes) -> list[bytes]:
    frames: list[bytes] = []
    start = data.find(b"$")
    while start >= 0:
        end = data.find(b"#", start)
        if end < 0:
            break
        frames.append(data[start:end + 1])
        start = data.find(b"$", end + 1)
    return frames


def serve(config: BridgeConfig) -> None:
    serial_fd: int | None = None
    serial_device = config.serial or find_serial_device()
    if not config.dry_run:
        if not serial_device:
            raise RuntimeError("no serial device found; pass --serial /dev/ttyXXX")
        serial_fd = open_serial(serial_device, config.baud)
        print(f"serial opened: {serial_device} @ {config.baud}")
    else:
        print("dry-run mode: frames will be printed, not written to serial")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((config.host, config.port))
        server.listen(8)
        print(f"TCP serial bridge listening on {config.host}:{config.port}")
        while True:
            client, address = server.accept()
            with client:
                print(f"client connected: {address}")
                while True:
                    data = client.recv(1024)
                    if not data:
                        break
                    for frame in extract_frames(data):
                        print(f"frame: {frame.decode('ascii', errors='ignore')}")
                        if serial_fd is not None:
                            os.write(serial_fd, frame)
                            time.sleep(0.02)
                        client.sendall(b"OK\n")


def parse_args() -> BridgeConfig:
    parser = argparse.ArgumentParser(description="Forward iCar TCP control frames to chassis serial without ROS2.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=6000)
    parser.add_argument("--serial", default=None, help="example: /dev/ttyUSB0, /dev/ttyTHS1")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return BridgeConfig(
        host=args.host,
        port=args.port,
        serial=args.serial,
        baud=args.baud,
        dry_run=args.dry_run,
    )


def main() -> None:
    serve(parse_args())


if __name__ == "__main__":
    main()
