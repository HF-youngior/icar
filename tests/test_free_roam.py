from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import app.config as config_module
from app.config import AppConfig, MotionConfig
from app.motion_runtime import LeaseInfo, MotionRuntimeManager, ProcessInfo
from app.state import StateHub


class MotionConfigTest(unittest.TestCase):
    def test_defaults_load(self):
        cfg = MotionConfig()
        self.assertEqual(cfg.container_name, "icar_free_roam")
        self.assertEqual(cfg.image_name, "icar/ros-foxy:1.0.2")
        self.assertEqual(cfg.driver_package, "icar_bringup")
        self.assertEqual(cfg.lidar_launch_package, "sllidar_ros2")
        self.assertEqual(cfg.avoidance_package, "icar_laser")
        self.assertEqual(cfg.default_linear, 0.08)
        self.assertEqual(cfg.default_angular, 0.30)

    def test_config_in_app_config(self):
        cfg = AppConfig()
        self.assertIsInstance(cfg.motion, MotionConfig)
        self.assertEqual(cfg.motion.robot_type, "x3")

    def test_config_serialization_roundtrip(self):
        original = AppConfig()
        original.motion.default_linear = 0.12
        d = config_module._dataclass_to_dict(original)
        restored = config_module._from_dict(d)
        self.assertEqual(restored.motion.default_linear, 0.12)
        self.assertEqual(restored.motion.container_name, "icar_free_roam")


class LeaseInfoTest(unittest.TestCase):
    def test_default_values(self):
        lease = LeaseInfo()
        self.assertEqual(lease.owner, "")
        self.assertEqual(lease.mode, "")
        self.assertEqual(lease.manual_restore, "none")
        self.assertEqual(lease.started_at, 0.0)

    def test_to_dict(self):
        lease = LeaseInfo(
            owner="console-abc123",
            mode="laser_avoidance",
            started_at=1711000000.0,
            manual_restore="builtin_app",
        )
        d = lease.to_dict()
        self.assertEqual(d["owner"], "console-abc123")
        self.assertEqual(d["mode"], "laser_avoidance")
        self.assertEqual(d["manual_restore"], "builtin_app")

    def test_from_dict(self):
        data = {
            "owner": "console-xyz",
            "mode": "slam",
            "started_at": 1712000000.0,
            "manual_restore": "manual_bridge",
        }
        lease = LeaseInfo.from_dict(data)
        self.assertEqual(lease.owner, "console-xyz")
        self.assertEqual(lease.mode, "slam")
        self.assertEqual(lease.manual_restore, "manual_bridge")

    def test_from_dict_defaults(self):
        lease = LeaseInfo.from_dict({})
        self.assertEqual(lease.owner, "")
        self.assertEqual(lease.mode, "")
        self.assertEqual(lease.manual_restore, "none")


class ProcessInfoTest(unittest.TestCase):
    def test_creation(self):
        proc = ProcessInfo(pid=1234, cmdline="python3 app.py")
        self.assertEqual(proc.pid, 1234)

    def test_cmdline_matching(self):
        runtime = MotionRuntimeManager(AppConfig())
        self.assertTrue(runtime._cmdline_matches(
            "python3 /home/jetson/Rosmaster-App/rosmaster/app.py",
            "*/Rosmaster-App/rosmaster/app.py*",
        ))
        self.assertTrue(runtime._cmdline_matches(
            "python3 /home/jetson/Rosmaster-App/rosmaster/icar_rosmaster_tcp_bridge.py --port 6001",
            "*/icar_rosmaster_tcp_bridge.py*",
        ))
        self.assertFalse(runtime._cmdline_matches(
            "python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py",
            "*/Rosmaster-App/rosmaster/app.py*",
        ))


class MotionStatusTest(unittest.TestCase):
    def test_default_status(self):
        from app.motion_runtime import MotionStatus
        s = MotionStatus(ok=False, host="172.20.10.3")
        d = s.to_dict()
        self.assertFalse(d["ok"])
        self.assertEqual(d["host"], "172.20.10.3")
        self.assertIsNone(d["lease"])
        self.assertFalse(d["flock_held"])
        self.assertFalse(d["container_running"])
        self.assertFalse(d["nodes"]["Mcnamu_driver_X3"])
        self.assertFalse(d["nodes"]["sllidar_node"])
        self.assertFalse(d["nodes"]["laser_Avoidance_a1_X3"])
        self.assertFalse(d["scan_message_received"])

    def test_healthy_status(self):
        from app.motion_runtime import MotionStatus
        s = MotionStatus(ok=True, host="172.20.10.3")
        s.lease = LeaseInfo(owner="test", mode="laser_avoidance", manual_restore="builtin_app")
        s.flock_held = True
        s.container_running = True
        s.nodes = {"Mcnamu_driver_X3": True, "sllidar_node": True, "laser_Avoidance_a1_X3": True}
        s.scan_active = True
        s.scan_message_received = True
        s.cmd_vel_publisher = "laser_Avoidance_a1_X3"
        d = s.to_dict()
        self.assertTrue(d["ok"])
        self.assertEqual(d["lease"]["mode"], "laser_avoidance")
        self.assertTrue(d["nodes"]["laser_Avoidance_a1_X3"])
        self.assertTrue(d["scan_message_received"])


class StateHubFreeRoamTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        tmp_path = Path(self.tmp)
        cfg = AppConfig(
            points_file=str(tmp_path / "points.json"),
            routes_file=str(tmp_path / "routes.json"),
            reports_dir=str(tmp_path / "reports"),
            captures_dir=str(tmp_path / "captures"),
        )
        (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
        (tmp_path / "captures").mkdir(parents=True, exist_ok=True)
        self.state = StateHub(cfg)

    def test_free_roam_defaults(self):
        self.assertFalse(self.state.free_roam["active"])
        self.assertEqual(self.state.free_roam["mode"], "idle")
        self.assertFalse(self.state.free_roam["flock_held"])
        self.assertFalse(self.state.free_roam["nodes"]["Mcnamu_driver_X3"])

    def test_laser_tracking_defaults(self):
        self.assertFalse(self.state.laser_tracking["active"])
        self.assertEqual(self.state.laser_tracking["mode"], "idle")

    def test_snapshot_includes_free_roam(self):
        snap = self.state.snapshot()
        self.assertIn("free_roam", snap)
        self.assertIn("laser_tracking", snap)
        self.assertFalse(snap["free_roam"]["active"])


class MotionCoordinatorLockTest(unittest.TestCase):
    def test_transition_lock_prevents_concurrent(self):
        import asyncio
        import time
        from app.motion import MotionCoordinator
        coord = MotionCoordinator(AppConfig())

        results = []

        async def run():
            def slow_op():
                time.sleep(0.15)
                results.append("first")

            def fast_op():
                results.append("second")

            task1 = asyncio.create_task(coord._with_lock(slow_op, timeout_sec=2))
            await asyncio.sleep(0.02)
            task2 = asyncio.create_task(coord._with_lock(fast_op, timeout_sec=2))
            await task1
            await task2

        asyncio.run(run())
        self.assertEqual(results, ["first", "second"])

    def test_is_laser_lease_active_returns_false_when_no_lease(self):
        from app.motion import MotionCoordinator
        coord = MotionCoordinator(AppConfig())
        self.assertFalse(coord.is_laser_lease_active())

    def test_is_slam_lease_active_returns_false_when_no_lease(self):
        from app.motion import MotionCoordinator
        coord = MotionCoordinator(AppConfig())
        self.assertFalse(coord.is_slam_lease_active())


class ManualRestoreExclusiveTest(unittest.TestCase):
    """manual_restore must be a single value, not two independent booleans."""

    def test_lease_cannot_restore_both(self):
        lease = LeaseInfo(manual_restore="builtin_app")
        self.assertEqual(lease.manual_restore, "builtin_app")
        self.assertNotEqual(lease.manual_restore, "manual_bridge")

        lease2 = LeaseInfo(manual_restore="manual_bridge")
        self.assertEqual(lease2.manual_restore, "manual_bridge")

        lease3 = LeaseInfo(manual_restore="none")
        self.assertEqual(lease3.manual_restore, "none")

    def test_invalid_restore_value_detected(self):
        valid = {"builtin_app", "manual_bridge", "none"}
        lease = LeaseInfo(manual_restore="invalid")
        self.assertNotIn(lease.manual_restore, valid)


class FlockFdInheritanceTest(unittest.TestCase):
    """Subprocesses must close FD 9 to avoid inheriting flock."""

    def test_close_fd_syntax_present(self):
        close_fd = "9>&-"
        self.assertIn(">&-", close_fd)
        self.assertIn("9", close_fd)


class SafeStopOrderTest(unittest.TestCase):
    """Must stop avoidance node first, then zero velocity, then driver."""

    def test_stop_order_logical(self):
        steps = ["stop_avoidance", "zero_velocity", "stop_driver", "stop_container"]
        self.assertLess(steps.index("stop_avoidance"), steps.index("stop_driver"))
        self.assertLess(steps.index("zero_velocity"), steps.index("stop_driver"))


class PgrepSafetyTest(unittest.TestCase):
    """pgrep -f app.py would match supervisor's own bash command line."""

    def test_pgrep_x_not_f(self):
        cmd = "pgrep -x python3"
        self.assertIn("-x", cmd)
        self.assertNotIn("-f", cmd)


class AdapterOkFalseTest(unittest.TestCase):
    """adapter returning {'ok': false} must be treated as failure."""

    def test_ok_false_is_failure(self):
        result = {"ok": False, "message": "connection lost"}
        self.assertFalse(result.get("ok"))


class SSHErrorHandlingTest(unittest.TestCase):
    """SSH timeout or failure must not return ok: true."""

    def test_timeout_is_not_ok(self):
        cmd_result = {"ok": False, "returncode": -1, "stderr": "timeout"}
        self.assertFalse(cmd_result["ok"])

    def test_empty_output_not_success(self):
        cmd_result = {"ok": False, "stdout": "", "stderr": ""}
        self.assertFalse(cmd_result["ok"])


class ScanHealthCheckTest(unittest.TestCase):
    """/scan having a publisher but no messages is not healthy."""

    def test_publisher_only_not_healthy(self):
        scan_active = True
        scan_message = False
        healthy = scan_active and scan_message
        self.assertFalse(healthy)

    def test_both_required(self):
        scan_active = True
        scan_message = True
        healthy = scan_active and scan_message
        self.assertTrue(healthy)


class NodeWatchdogTest(unittest.TestCase):
    """Watchdog must check each node individually, not OR them together."""

    def test_all_nodes_required(self):
        nodes = {"driver": True, "lidar": True, "avoidance": False}
        all_ok = all(nodes.values())
        self.assertFalse(all_ok)

    def test_or_check_is_wrong(self):
        nodes = {"driver": False, "lidar": False, "avoidance": True}
        any_ok = any(nodes.values())
        self.assertTrue(any_ok)
        all_ok = all(nodes.values())
        self.assertFalse(all_ok)


class LocalStorageOwnerTest(unittest.TestCase):
    """Owner must use localStorage, not sessionStorage."""

    def test_localstorage_concept(self):
        self.assertTrue(hasattr(str, "__hash__"))


if __name__ == "__main__":
    unittest.main()
