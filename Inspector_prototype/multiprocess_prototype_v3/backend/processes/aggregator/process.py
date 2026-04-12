# multiprocess_prototype_v3/backend/processes/aggregator/process.py
"""Сбор статистики инспекции, опционально SQLite (stage 6)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig


class AggregatorProcess(ProcessModule):
    """Считает кадры/defects, периодический отчёт, запись в БД при включении."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._sql = None

    def _init_application_threads(self) -> None:
        self._frames = 0
        self._defects = 0
        self._report_interval = float(self.get_config("report_interval", 2.0))
        self._persist = bool(self.get_config("persist_detections", False))
        self._last_report = time.monotonic()

        self.command_manager.register_command("register_update", self._apply_register_update)
        self.command_manager.register_command("get_report", self._cmd_get_report)

        if self._persist:
            self._init_sql()

        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker("aggregate", self._aggregate_loop, cfg, auto_start=True)

    def _init_sql(self) -> None:
        try:
            from multiprocess_framework.modules.sql_module import (
                SQLManager,
                SQLManagerConfig,
            )

            from multiprocess_prototype_v3.persistence.paths import (
                detections_db_url,
                ensure_data_dir,
            )

            ensure_data_dir()
            url = detections_db_url()
            cfg = SQLManagerConfig(url=url, fork_safe=True, pool_size=1, max_overflow=0)
            self._sql = SQLManager(
                manager_name=f"sql_{self.name}",
                config=cfg,
                managers={"logger": self.logger_manager} if self.logger_manager else {},
                process=self,
            )
            self._sql.initialize()
            self._sql.execute(
                """
                CREATE TABLE IF NOT EXISTS detections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    frame_id INTEGER NOT NULL,
                    brightness REAL NOT NULL,
                    is_defect INTEGER NOT NULL,
                    ts TEXT NOT NULL
                )
                """
            )
        except Exception as e:
            self._log_error(f"SQL init failed: {e}")
            self._sql = None

    def _apply_register_update(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(data, dict):
            return {"status": "error", "reason": "invalid payload"}
        field = data.get("field_name") or data.get("field")
        value = data.get("value")
        if field == "report_interval":
            self._report_interval = float(value)
            self.update_config("report_interval", self._report_interval)
        return {"status": "ok", "field": field}

    def _cmd_get_report(self, _data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if self._sql:
            try:
                rows: List[Dict[str, Any]] = self._sql.query(
                    "SELECT frame_id, brightness, is_defect, ts FROM detections ORDER BY id DESC LIMIT 20"
                )
                return {"status": "ok", "rows": rows, "frames": self._frames, "defects": self._defects}
            except Exception as e:
                return {"status": "error", "reason": str(e)}
        return {
            "status": "ok",
            "rows": [],
            "frames": self._frames,
            "defects": self._defects,
        }

    def _aggregate_loop(self, stop_event, pause_event) -> None:
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue
            msgs = self.receive(timeout=0.2, channel_types=["data"])
            now = time.monotonic()
            for msg in msgs:
                if not isinstance(msg, dict):
                    continue
                if msg.get("data_type") != "inspection_result":
                    continue
                body = msg.get("data") or {}
                if not isinstance(body, dict):
                    continue
                self._frames += 1
                is_defect = bool(body.get("is_defect"))
                if is_defect:
                    self._defects += 1
                if self._sql:
                    try:
                        ts = datetime.now(timezone.utc).isoformat()
                        self._sql.execute(
                            """
                            INSERT INTO detections (frame_id, brightness, is_defect, ts)
                            VALUES (:frame_id, :brightness, :is_defect, :ts)
                            """,
                            {
                                "frame_id": int(body.get("frame_id", 0)),
                                "brightness": float(body.get("brightness", 0.0)),
                                "is_defect": 1 if is_defect else 0,
                                "ts": ts,
                            },
                        )
                    except Exception as e:
                        self._log_error(f"SQL insert failed: {e}")
            if now - self._last_report >= self._report_interval:
                self._last_report = now
                self._log_info(
                    f"Summary: frames={self._frames} defects={self._defects} "
                    f"defect_rate={(self._defects / self._frames) if self._frames else 0:.3f}"
                )
            time.sleep(0.01)

    def shutdown(self) -> bool:
        if self._sql:
            try:
                self._sql.shutdown()
            except Exception:
                pass
            self._sql = None
        return super().shutdown()
