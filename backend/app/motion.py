from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .config import AppConfig
from .motion_runtime import MotionRuntimeManager, MotionStatus

logger = logging.getLogger(__name__)


class MotionCoordinator:
    """FastAPI 进程内避障 / SLAM / 手控协调层。

    持有 transition_lock 防止并发模式切换。
    通过 MotionRuntimeManager 操作 Jetson 远端资源。
    """

    def __init__(self, config: AppConfig, slam_runtime: Any = None) -> None:
        self.config = config
        self.runtime = MotionRuntimeManager(config)
        self._slam_runtime = slam_runtime
        self._transition_lock = asyncio.Lock()
        self._health_task: asyncio.Task[None] | None = None
        self._health_failures = 0
        self._active_owner: str = ""

    # ── Transition lock helpers ──────────────────────────────────

    async def _with_lock(self, coro, timeout_sec: float = 60.0) -> Any:
        """Acquire _transition_lock then run coro in thread pool."""
        try:
            await asyncio.wait_for(self._transition_lock.acquire(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            raise RuntimeError("transition_lock timed out — another motion operation in progress")
        try:
            return await asyncio.to_thread(coro)
        finally:
            self._transition_lock.release()

    # ── Status ───────────────────────────────────────────────────

    async def status(self) -> dict[str, Any]:
        def _status() -> dict[str, Any]:
            return self.runtime.status().to_dict()

        return await asyncio.to_thread(_status)

    # ── Start ────────────────────────────────────────────────────

    async def start(self, owner: str = "", linear: float = 0, angular: float = 0) -> dict[str, Any]:

        def _start() -> dict[str, Any]:
            if self._slam_runtime is not None:
                try:
                    slam_status = self._slam_runtime.status()
                    if slam_status.get("mode", "idle") not in ("idle",):
                        logger.info("stopping SLAM (mode=%s) before laser avoidance", slam_status.get("mode"))
                        self._slam_runtime.stop()
                        time.sleep(1)
                except Exception as exc:
                    logger.warning("SLAM stop before avoidance: %s", exc)

            result = self.runtime.start_laser_avoidance(owner=owner, linear=linear, angular=angular)
            if result.get("ok"):
                self._active_owner = owner
                self._health_failures = 0
            return result

        result = await self._with_lock(_start, timeout_sec=90.0)
        if result.get("ok"):
            self._start_health_loop()
        return result

    # ── Stop ─────────────────────────────────────────────────────

    async def stop(self, emergency: bool = False) -> dict[str, Any]:

        def _stop() -> dict[str, Any]:
            self._stop_health_loop()
            result = self.runtime.stop_laser_avoidance(emergency=emergency)
            self._active_owner = ""
            self._health_failures = 0
            return result

        return await self._with_lock(_stop, timeout_sec=60.0)

    # ── Emergency stop ───────────────────────────────────────────

    async def emergency_stop(self, reason: str = "web") -> dict[str, Any]:
        return await self.stop(emergency=True)

    # ── Health loop (background) ─────────────────────────────────

    def _start_health_loop(self) -> None:
        if self._health_task is None or self._health_task.done():
            self._health_task = asyncio.create_task(self._health_loop())

    def _stop_health_loop(self) -> None:
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            self._health_task = None

    async def _health_loop(self) -> None:
        interval = self.config.motion.health_poll_interval_sec
        threshold = self.config.motion.health_failure_threshold
        while True:
            await asyncio.sleep(interval)
            try:
                status = await asyncio.to_thread(self.runtime._quick_check)
                if status.ok:
                    self._health_failures = 0
                else:
                    self._health_failures += 1
                    logger.warning("motion health check failed (%d/%d): %s",
                                   self._health_failures, threshold, status.message)
                    if self._health_failures >= threshold:
                        logger.error("motion health failures reached threshold; triggering fail-safe stop")
                        asyncio.create_task(self._fail_safe_stop())
                        return
            except asyncio.CancelledError:
                return
            except Exception as exc:
                self._health_failures += 1
                logger.exception("motion health check exception (%d/%d)", self._health_failures, threshold)
                if self._health_failures >= threshold:
                    asyncio.create_task(self._fail_safe_stop())
                    return

    async def _fail_safe_stop(self) -> None:
        try:
            lease = self.runtime._read_lease()
            if lease and lease.mode == "laser_tracking":
                await self.stop_tracking(emergency=True)
            else:
                await self.stop(emergency=True)
        except Exception:
            logger.exception("fail-safe stop failed")

    # ── Laser tracking ────────────────────────────────────────────

    async def start_tracking(self, owner: str = "") -> dict[str, Any]:

        def _start() -> dict[str, Any]:
            if self._slam_runtime is not None:
                try:
                    slam_status = self._slam_runtime.status()
                    if slam_status.get("mode", "idle") not in ("idle",):
                        logger.info("stopping SLAM before laser tracking")
                        self._slam_runtime.stop()
                        time.sleep(1)
                except Exception as exc:
                    logger.warning("SLAM stop before tracking: %s", exc)
            result = self.runtime.start_laser_tracking(owner=owner)
            if result.get("ok"):
                self._active_owner = owner
                self._health_failures = 0
            return result

        result = await self._with_lock(_start, timeout_sec=90.0)
        if result.get("ok"):
            self._start_health_loop()
        return result

    async def stop_tracking(self, emergency: bool = False) -> dict[str, Any]:

        def _stop() -> dict[str, Any]:
            self._stop_health_loop()
            result = self.runtime.stop_laser_tracking(emergency=emergency)
            self._active_owner = ""
            self._health_failures = 0
            return result

        return await self._with_lock(_stop, timeout_sec=60.0)

    # ── SLAM handoff ─────────────────────────────────────────────

    def set_slam_runtime(self, slam_runtime: Any) -> None:
        self._slam_runtime = slam_runtime

    # ── Lease check (for manual control gating) ──────────────────

    def is_laser_lease_active(self) -> bool:
        lease = self.runtime._read_lease()
        return lease is not None and lease.mode in ("laser_avoidance", "laser_tracking")

    def is_slam_lease_active(self) -> bool:
        lease = self.runtime._read_lease()
        return lease is not None and lease.mode == "slam"
