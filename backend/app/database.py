from __future__ import annotations

import json
from typing import Any

from .config import DatabaseConfig


class DatabaseStore:
    def __init__(self, config: DatabaseConfig) -> None:
        self.config = config
        self.available = False
        self.last_error: str | None = None

    def _connect(self):
        import pymysql

        return pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            database=self.config.database,
            charset=self.config.charset,
            connect_timeout=self.config.connect_timeout_sec,
            autocommit=True,
        )

    def init_schema(self) -> None:
        if not self.config.enabled:
            return
        statements = [
            """
            CREATE TABLE IF NOT EXISTS robot_alarm (
              id BIGINT PRIMARY KEY AUTO_INCREMENT,
              alarm_id VARCHAR(64) NOT NULL UNIQUE,
              type VARCHAR(64) NOT NULL,
              level VARCHAR(32) NOT NULL,
              message TEXT NOT NULL,
              source VARCHAR(64) NOT NULL,
              status VARCHAR(32) NOT NULL,
              metadata JSON NULL,
              created_at DATETIME NOT NULL,
              confirmed_by VARCHAR(64) NULL,
              confirmed_at DATETIME NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS robot_report (
              id BIGINT PRIMARY KEY AUTO_INCREMENT,
              report_id VARCHAR(64) NOT NULL UNIQUE,
              title VARCHAR(255) NOT NULL,
              summary TEXT NOT NULL,
              details JSON NULL,
              created_at DATETIME NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS robot_vision_event (
              id BIGINT PRIMARY KEY AUTO_INCREMENT,
              event_id VARCHAR(64) NOT NULL UNIQUE,
              label VARCHAR(128) NOT NULL,
              label_zh VARCHAR(128) NULL,
              confidence DOUBLE NULL,
              risk VARCHAR(32) NULL,
              bbox JSON NULL,
              image_url VARCHAR(512) NULL,
              source VARCHAR(64) NULL,
              created_at DATETIME NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS robot_sensor_sample (
              id BIGINT PRIMARY KEY AUTO_INCREMENT,
              sensor_name VARCHAR(64) NOT NULL,
              label VARCHAR(128) NULL,
              value DOUBLE NOT NULL,
              unit VARCHAR(32) NULL,
              level VARCHAR(32) NULL,
              created_at DATETIME NOT NULL,
              INDEX idx_sensor_time(sensor_name, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS robot_cruise_route (
              id BIGINT PRIMARY KEY AUTO_INCREMENT,
              route_id VARCHAR(64) NOT NULL UNIQUE,
              name VARCHAR(128) NOT NULL,
              payload JSON NOT NULL,
              updated_at DATETIME NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
        ]
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    for statement in statements:
                        cursor.execute(statement)
            self.available = True
            self.last_error = None
        except Exception as exc:
            self.available = False
            self.last_error = str(exc)

    def health(self) -> dict[str, Any]:
        if not self.config.enabled:
            return {"enabled": False, "available": False, "message": "database disabled"}
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
            self.available = True
            self.last_error = None
        except Exception as exc:
            self.available = False
            self.last_error = str(exc)
        return {
            "enabled": self.config.enabled,
            "available": self.available,
            "host": self.config.host,
            "port": self.config.port,
            "database": self.config.database,
            "last_error": self.last_error,
        }

    def save_alarm(self, alarm: dict[str, Any]) -> None:
        if not self.config.enabled:
            return
        sql = """
            INSERT INTO robot_alarm
              (alarm_id, type, level, message, source, status, metadata, created_at, confirmed_by, confirmed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              status=VALUES(status), confirmed_by=VALUES(confirmed_by), confirmed_at=VALUES(confirmed_at)
        """
        self._execute(sql, (
            alarm.get("alarm_id"),
            alarm.get("type"),
            alarm.get("level"),
            alarm.get("message"),
            alarm.get("source"),
            alarm.get("status"),
            json.dumps(alarm.get("metadata") or {}, ensure_ascii=False),
            alarm.get("timestamp"),
            alarm.get("confirmed_by"),
            alarm.get("confirmed_at"),
        ))

    def save_report(self, report: dict[str, Any]) -> None:
        if not self.config.enabled:
            return
        sql = """
            INSERT INTO robot_report (report_id, title, summary, details, created_at)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE summary=VALUES(summary), details=VALUES(details)
        """
        self._execute(sql, (
            report.get("report_id"),
            report.get("title"),
            report.get("summary"),
            json.dumps(report.get("details") or {}, ensure_ascii=False),
            report.get("timestamp"),
        ))

    def save_vision_event(self, event: dict[str, Any]) -> None:
        if not self.config.enabled:
            return
        sql = """
            INSERT INTO robot_vision_event
              (event_id, label, label_zh, confidence, risk, bbox, image_url, source, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE confidence=VALUES(confidence)
        """
        self._execute(sql, (
            event.get("id"),
            event.get("label"),
            event.get("label_zh"),
            event.get("confidence"),
            event.get("risk"),
            json.dumps(event.get("bbox") or [], ensure_ascii=False),
            event.get("image_url"),
            event.get("source"),
            event.get("timestamp"),
        ))

    def save_sensor_sample(self, sample: dict[str, Any]) -> None:
        if not self.config.enabled:
            return
        value = sample.get("value")
        if value is None:
            return
        sql = """
            INSERT INTO robot_sensor_sample (sensor_name, label, value, unit, level, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        self._execute(sql, (
            sample.get("name"),
            sample.get("label"),
            float(value),
            sample.get("unit"),
            sample.get("level"),
            sample.get("updated_at"),
        ))

    def save_cruise_route(self, route: dict[str, Any]) -> None:
        if not self.config.enabled:
            return
        sql = """
            INSERT INTO robot_cruise_route (route_id, name, payload, updated_at)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE name=VALUES(name), payload=VALUES(payload), updated_at=VALUES(updated_at)
        """
        self._execute(sql, (
            route.get("id"),
            route.get("name"),
            json.dumps(route, ensure_ascii=False),
            route.get("updated_at"),
        ))

    def list_cruise_routes(self) -> list[dict[str, Any]]:
        if not self.config.enabled:
            return []
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT payload FROM robot_cruise_route ORDER BY updated_at DESC")
                    rows = cursor.fetchall()
            self.available = True
            self.last_error = None
            routes: list[dict[str, Any]] = []
            for row in rows:
                raw = row[0] if isinstance(row, tuple) else row.get("payload")
                data = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(data, dict):
                    routes.append(data)
            return routes
        except Exception as exc:
            self.available = False
            self.last_error = str(exc)
            return []

    def _execute(self, sql: str, params: tuple[Any, ...]) -> None:
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, params)
            self.available = True
            self.last_error = None
        except Exception as exc:
            self.available = False
            self.last_error = str(exc)


class NullDatabaseStore(DatabaseStore):
    def __init__(self) -> None:
        super().__init__(DatabaseConfig(enabled=False))

    def init_schema(self) -> None:
        return None

    def health(self) -> dict[str, Any]:
        return {"enabled": False, "available": False, "message": "database disabled"}

    def save_alarm(self, alarm: dict[str, Any]) -> None:
        return None

    def save_report(self, report: dict[str, Any]) -> None:
        return None

    def save_vision_event(self, event: dict[str, Any]) -> None:
        return None

    def save_sensor_sample(self, sample: dict[str, Any]) -> None:
        return None

    def save_cruise_route(self, route: dict[str, Any]) -> None:
        return None

    def list_cruise_routes(self) -> list[dict[str, Any]]:
        return []
