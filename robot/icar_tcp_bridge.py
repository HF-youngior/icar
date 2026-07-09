#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

import rclpy
from geometry_msgs.msg import Twist


@dataclass
class BridgeConfig:
    host: str
    port: int
    topic: str
    linear_speed: float
    angular_speed: float
    strafe_speed: float


class IcarTcpBridge:
    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        rclpy.init()
        self.node = rclpy.create_node("icar_tcp_bridge")
        self.publisher = self.node.create_publisher(Twist, config.topic, 10)

    async def run(self) -> None:
        server = await asyncio.start_server(self.handle_client, self.config.host, self.config.port)
        addresses = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
        self.node.get_logger().info(f"iCar TCP bridge listening on {addresses}, publishing {self.config.topic}")
        async with server:
            await server.serve_forever()

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        try:
            while data := await reader.read(1024):
                text = data.decode("utf-8", errors="ignore")
                for frame in self.extract_frames(text):
                    direction = self.decode_button_frame(frame)
                    if direction is None:
                        self.node.get_logger().warning(f"ignored frame from {peer}: {frame}")
                        continue
                    self.node.get_logger().info(f"command from {peer}: {direction}")
                    self.publisher.publish(self.to_twist(direction))
                    writer.write(f"OK {direction}\n".encode("utf-8"))
                    await writer.drain()
        except ConnectionResetError:
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    def extract_frames(self, text: str) -> list[str]:
        frames: list[str] = []
        start = text.find("$")
        while start >= 0:
            end = text.find("#", start)
            if end < 0:
                break
            frames.append(text[start:end + 1])
            start = text.find("$", end + 1)
        return frames

    def decode_button_frame(self, frame: str) -> str | None:
        if len(frame) < 10 or not frame.startswith("$") or not frame.endswith("#"):
            return None
        body = frame[1:-1]
        if len(body) % 2 != 0 or len(body) < 8:
            return None
        payload = body[:-2]
        checksum = body[-2:].upper()
        if self.checksum(payload) != checksum:
            self.node.get_logger().warning(f"bad checksum: {frame}, expected {self.checksum(payload)}")
            return None
        command = payload[2:4]
        if command != "15":
            return None
        direction_hex = payload[6:8]
        return {
            "00": "stop",
            "01": "forward",
            "02": "backward",
            "03": "left",
            "04": "right",
            "05": "left_rotate",
            "06": "right_rotate",
            "07": "brake",
        }.get(direction_hex)

    def checksum(self, payload: str) -> str:
        total = 0
        for index in range(0, len(payload), 2):
            total = (total + int(payload[index:index + 2], 16)) % 256
        return f"{total:02X}"

    def to_twist(self, direction: str) -> Twist:
        msg = Twist()
        if direction == "forward":
            msg.linear.x = self.config.linear_speed
        elif direction == "backward":
            msg.linear.x = -self.config.linear_speed
        elif direction == "left":
            msg.linear.y = self.config.strafe_speed
        elif direction == "right":
            msg.linear.y = -self.config.strafe_speed
        elif direction == "left_rotate":
            msg.angular.z = self.config.angular_speed
        elif direction == "right_rotate":
            msg.angular.z = -self.config.angular_speed
        return msg

    def close(self) -> None:
        self.publisher.publish(Twist())
        self.node.destroy_node()
        rclpy.shutdown()


def parse_args() -> BridgeConfig:
    parser = argparse.ArgumentParser(description="Bridge Harmony/Web TCP control frames to ROS2 /cmd_vel.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=6000)
    parser.add_argument("--topic", default="/cmd_vel")
    parser.add_argument("--linear-speed", type=float, default=0.16)
    parser.add_argument("--angular-speed", type=float, default=0.55)
    parser.add_argument("--strafe-speed", type=float, default=0.12)
    args = parser.parse_args()
    return BridgeConfig(
        host=args.host,
        port=args.port,
        topic=args.topic,
        linear_speed=args.linear_speed,
        angular_speed=args.angular_speed,
        strafe_speed=args.strafe_speed,
    )


def main() -> None:
    bridge = IcarTcpBridge(parse_args())
    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        pass
    finally:
        bridge.close()


if __name__ == "__main__":
    main()
