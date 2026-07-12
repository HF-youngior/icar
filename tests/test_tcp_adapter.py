from __future__ import annotations

import unittest

from tests import BACKEND  # noqa: F401

from app.adapters.tcp_car import TcpCarAdapter
from app.config import CarConfig


class TcpCarAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = TcpCarAdapter(CarConfig())

    def test_encodes_motion_command_frames(self) -> None:
        self.assertEqual(
            self.adapter._command_payloads("forward", speed=0.16),
            ["$011606323281#", "$011504011B#"],
        )
        self.assertEqual(self.adapter._command_payloads("stop"), ["$011504001A#"])
        self.assertEqual(
            self.adapter._command_payloads("left", speed=0.32),
            ["$0116066464E5#", "$011504051F#"],
        )

    def test_rejects_unsupported_command(self) -> None:
        with self.assertRaises(ValueError):
            self.adapter._command_payloads("dance")

    def test_hex_padding(self) -> None:
        self.assertEqual(self.adapter._hex(7), "07")
        self.assertEqual(self.adapter._hex(255), "FF")

    def test_speed_percent_clamps_values(self) -> None:
        self.assertEqual(self.adapter._speed_percent(-1), 0)
        self.assertEqual(self.adapter._speed_percent(0.16), 50)
        self.assertEqual(self.adapter._speed_percent(0.32), 100)
        self.assertEqual(self.adapter._speed_percent(160), 100)


if __name__ == "__main__":
    unittest.main()
