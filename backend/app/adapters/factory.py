from __future__ import annotations

from ..config import AppConfig
from .base import CarAdapter
from .ros2_cli import Ros2CliCarAdapter
from .simulated import SimulatedCarAdapter
from .tcp_car import TcpCarAdapter


def build_adapter(config: AppConfig) -> CarAdapter:
    adapter = config.car.adapter.lower().strip()
    if adapter == "simulated":
        return SimulatedCarAdapter()
    if adapter == "tcp":
        return TcpCarAdapter(config.car)
    if adapter == "ros2_cli":
        return Ros2CliCarAdapter(config.car)
    raise ValueError(f"Unsupported car adapter: {config.car.adapter}")

