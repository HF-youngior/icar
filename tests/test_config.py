from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import BACKEND  # noqa: F401

from app.config import load_config, read_json_file


class ConfigTest(unittest.TestCase):
    def test_load_config_merges_file_and_environment_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "app.json"
            config_path.write_text(
                json.dumps({
                    "server": {"host": "127.0.0.1", "port": 9000},
                    "car": {"adapter": "tcp", "host": "192.168.1.20", "port": 6000},
                    "sensor_tick_sec": 2.5,
                }),
                encoding="utf-8",
            )
            env = {
                "ICAR_CONFIG": str(config_path),
                "ICAR_CAR_ADAPTER": "ros2_cli",
                "ICAR_PORT": "7000",
                "ICAR_DB_HOST": "db.example.com",
                "ICAR_DB_PORT": "3307",
                "ICAR_DB_USER": "icar",
                "ICAR_DB_PASSWORD": "secret",
                "ICAR_DB_NAME": "robot",
            }
            with patch.dict(os.environ, env, clear=True):
                config = load_config()

        self.assertEqual(config.server.host, "127.0.0.1")
        self.assertEqual(config.server.port, 7000)
        self.assertEqual(config.car.adapter, "ros2_cli")
        self.assertEqual(config.car.host, "192.168.1.20")
        self.assertEqual(config.sensor_tick_sec, 2.5)
        self.assertTrue(config.database.enabled)
        self.assertEqual(config.database.host, "db.example.com")
        self.assertEqual(config.database.port, 3307)
        self.assertEqual(config.database.user, "icar")
        self.assertEqual(config.database.password, "secret")
        self.assertEqual(config.database.database, "robot")

    def test_read_json_file_returns_fallback_for_missing_file(self) -> None:
        self.assertEqual(read_json_file("/tmp/icar-missing-test-file.json", {"ok": False}), {"ok": False})


if __name__ == "__main__":
    unittest.main()
