"""TelemetrySinkPlugin — сток истории телеметрии в БД через SQLManager.

Side-effect плагин (НЕ источник кадров, нет inputs/outputs): живёт в обычном
GenericProcessApp-процессе. Подписывается на дерево StateStore (`processes.**`)
через тот же IPC-механизм `state.subscribe`, что и GUI, по таймеру семплит
снимок кэша подписки и батчево пишет историю в SQLite через Services/sql.

Архитектура потока данных::

    StateStoreManager --state.changed--> ctx.state_proxy.subscribe callback
        --> self._cache[path] = value          (только запись в кэш, без I/O)
    loop-worker (sample_interval_sec)
        --> снимок _cache --> TelemetrySnapshot[] --> repo.insert_many (sync)

Fork-safety (КРИТИЧНО): SQLManager создаётся и initialize()/create_tables()
вызываются ВНУТРИ start() — ПОСЛЕ fork дочернего процесса, НЕ в configure().
Конфиг с fork_safe=True (NullPool) + check_same_thread=False (subscribe-callback
и sample-worker — разные потоки одного процесса).

Task 1.2: на каждом семпле — строка на каждый процесс (fps/latency_ms/uptime_s/
status + нестандартный хвост workers.* в extra JSON) + отдельная строка-сводка
process_name='system' из system.health.* (fps←avg_fps, остальное в extra).
Task 1.3: команды flush/get_stats/purge_old + register-параметр retention_days
(0 = без ретенции; purge_old — ручная очистка, scheduled-ротация — отдельный /plan).
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from multiprocess_framework.modules.process_module.plugins import (
    ExecutionMode,
    PluginContext,
    ProcessModulePlugin,
    ThreadConfig,
    register_plugin,
)

from Services.sql import SQLManager, SQLManagerConfig

from .registers import TelemetrySinkRegisters
from .schemas import TelemetrySnapshot

if TYPE_CHECKING:
    from multiprocess_framework.modules.state_store_module.core.delta import Delta


@register_plugin(
    "telemetry_sink",
    category="output",
    description="Сток истории телеметрии StateStore в SQLite (SQLManager)",
)
class TelemetrySinkPlugin(ProcessModulePlugin):
    """Подписка на дерево телеметрии → семпл по таймеру → запись в БД."""

    name = "telemetry_sink"
    category = "output"

    # Side-effect плагин: данные приходят через подписку StateStore, не через порты.
    inputs = []
    outputs = []

    register_class = TelemetrySinkRegisters

    # Команды плагина (имя → метод). Маршрутизируются CommandManager'ом процесса.
    commands = {
        "flush": "_cmd_flush",
        "get_stats": "_cmd_get_stats",
        "purge_old": "_cmd_purge_old",
    }

    def configure(self, ctx: PluginContext) -> None:
        """READY: register + кэш подписки + lock. SQLManager НЕ создаём (fork!)."""
        self._ctx = ctx
        self._reg = self._init_register(ctx)

        # Свой кэш листьев подписки: path -> value (НЕ переиспользуем внутренний
        # StateProxy._cache намеренно — нужен собственный lock и точка снятия снимка
        # под семпл, независимая от внутренней логики proxy). Заполняется callback'ом,
        # читается sample-worker'ом → под _cache_lock (разные потоки одного процесса).
        self._cache: dict[str, object] = {}
        self._cache_lock = threading.Lock()
        # Сериализует запись (sample-worker vs _cmd_flush): без него возможны
        # дубль-вставки снимка и потеря инкремента счётчика.
        self._write_lock = threading.Lock()

        # Создаются в start() после fork — здесь только объявляем.
        self._sql: SQLManager | None = None
        self._sub_id: str | None = None
        self._sub_id_system: str | None = None
        self._total_written: int = 0
        self._last_ts: float = 0.0  # ts последнего успешного семпла (для get_stats)

        # Директорию под БД создаём заранее (путь относительный к cwd процесса).
        db_file = Path(self._reg.db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

        ctx.log_info(f"TelemetrySinkPlugin: db={self._reg.db_path}, sample_interval={self._reg.sample_interval_sec}s")

    def start(self, ctx: PluginContext) -> None:
        """RUNNING: создать SQLManager (после fork), подписаться, запустить worker."""
        # --- 1. SQLManager ВНУТРИ процесса, fork-safe (решение (г) плана) ---
        config = SQLManagerConfig(
            url=f"sqlite:///{self._reg.db_path}",
            dialect="sqlite",
            fork_safe=True,  # NullPool — обязательно после fork
            connect_args={"check_same_thread": False},
        )
        self._sql = SQLManager(config=config, managers={}, process=None)
        self._sql.initialize()
        self._sql.create_tables([TelemetrySnapshot])

        # --- 2. Подписка на дерево телеметрии ---
        if ctx.state_proxy is None:
            # Edge case: процесс без StateProxy → плагин работает как no-op,
            # не падает. БД создана, но без подписки семплить нечего.
            ctx.log_error(
                "TelemetrySinkPlugin: ctx.state_proxy is None — подписка невозможна, "
                "плагин работает как no-op (история не пишется)"
            )
        else:
            self._sub_id = ctx.state_proxy.subscribe("processes.**", self._on_deltas, exclude_self=True)
            # system.** — сводное здоровье (avg_fps/active/broken_wires) для строки
            # process_name='system'. Тот же callback кладёт листья в общий кэш.
            self._sub_id_system = ctx.state_proxy.subscribe("system.**", self._on_deltas, exclude_self=True)
            ctx.log_info(
                f"TelemetrySinkPlugin: подписка 'processes.**'/'system.**' sub_id={self._sub_id}/{self._sub_id_system}"
            )

        # --- 3. Loop-worker семпла кэша по таймеру (как DatabasePlugin._flush_loop) ---
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker("telemetry_sample_worker", self._sample_loop, cfg, auto_start=True)
        ctx.log_info("TelemetrySinkPlugin: started, таблица telemetry_snapshots готова")

    def shutdown(self, ctx: PluginContext) -> None:
        """STOPPED: финальный семпл, закрыть SQLManager. Unsubscribe делает proxy."""
        # Финальный семпл — не потерять последнее окно данных.
        try:
            self._sample_once()
        except Exception as exc:  # pragma: no cover — defensive на shutdown
            ctx.log_error(f"TelemetrySinkPlugin: финальный семпл упал: {exc}")

        if self._sql is not None:
            self._sql.shutdown()
            self._sql = None
        ctx.log_info(f"TelemetrySinkPlugin: shutdown, всего строк записано: {self._total_written}")

    # --- Подписка ---

    def _on_deltas(self, deltas: list[Delta]) -> None:
        """Callback подписки: только кладём листья в кэш, без I/O.

        Тяжёлая работа (запись в БД) вынесена в sample-worker, чтобы не блокировать
        IPC-поток state.changed на каждой дельте.
        """
        with self._cache_lock:
            for d in deltas:
                # Удаление узла (new_value is MISSING) → убираем из кэша.
                if d.is_delete:
                    self._cache.pop(d.path, None)
                else:
                    self._cache[d.path] = d.new_value

    # --- Семпл ---

    def _sample_loop(self, stop_event, pause_event) -> None:
        """Периодический семпл кэша (как DatabasePlugin._flush_loop).

        `_sample_once` обёрнут в try/except: транзиентная ошибка БД (locked, и т.п.)
        НЕ должна убивать worker — иначе сток телеметрии молча умрёт навсегда.
        Логируем и продолжаем до следующего тика. (repo.insert_many — per-row commit,
        не атомарна: частичная запись возможна, но следующий семпл — новый ts-снимок,
        не повтор, поэтому дублей нет.)
        """
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            time.sleep(self._reg.sample_interval_sec)
            try:
                self._sample_once()
            except Exception as exc:
                self._ctx.log_error(f"TelemetrySinkPlugin: семпл упал, продолжаю: {exc}")

    # Стандартные метрики `processes.<P>.state.<metric>` → колонки.
    # uptime маппится в колонку uptime_s; остальные state.* и все workers.* — в extra.
    _STATE_COLS = ("fps", "latency_ms", "uptime", "status")

    def _sample_once(self) -> int:
        """Снять снимок кэша → строки TelemetrySnapshot → insert_many.

        Одна строка на каждый процесс (из `processes.<P>.state.*` + `workers.*`)
        + строка-сводка `process_name='system'` (из `system.health.*`).
        Возвращает число записанных строк.
        """
        if self._sql is None:
            return 0

        # _write_lock сериализует семплы из sample-worker и из _cmd_flush:
        # иначе два потока берут снимок и пишут его параллельно → дубль-строки
        # и потерянный инкремент _total_written (неатомарный read-modify-write).
        with self._write_lock:
            # Снимок кэша под cache-lock — дальше работаем с копией без удержания.
            with self._cache_lock:
                snapshot = dict(self._cache)

            # Группируем кэш: per-process метрики + сводка system.health.
            procs: dict[str, dict[str, object]] = {}
            system_health: dict[str, object] = {}
            for path, value in snapshot.items():
                parts = path.split(".")
                if parts[0] == "processes" and len(parts) >= 4:
                    pname, section = parts[1], parts[2]
                    if section == "state":
                        entry = procs.setdefault(pname, {})
                        # Ровно processes.<P>.state.<known> → колонка; неизвестный
                        # или вложенный state-лист → extra (не теряем данные).
                        if len(parts) == 4 and parts[3] in self._STATE_COLS:
                            entry[parts[3]] = value
                        else:
                            entry.setdefault("_extra", {})[".".join(parts[2:])] = value  # type: ignore[union-attr]
                    elif section == "workers":
                        # Нестандартный per-worker хвост → extra JSON.
                        entry = procs.setdefault(pname, {})
                        entry.setdefault("_extra", {})[".".join(parts[2:])] = value  # type: ignore[union-attr]
                    # config.* и прочие секции — не телеметрия, пропускаем.
                elif parts[0] == "system" and len(parts) >= 3 and parts[1] == "health":
                    system_health[".".join(parts[2:])] = value
                # прочее system.* (stop_timeout/shm_budget_mb/log_dir) — статика, пропускаем.

            ts = time.time()
            rows: list[TelemetrySnapshot] = [self._build_proc_row(ts, pname, entry) for pname, entry in procs.items()]
            if system_health:
                rows.append(self._build_system_row(ts, system_health))

            # Edge case: кэш пуст → не пишем пустые строки.
            if not rows:
                return 0

            repo = self._sql.get_repository(TelemetrySnapshot)
            repo.insert_many(rows)
            self._total_written += len(rows)
            self._last_ts = ts
            return len(rows)

    # --- Команды (имя → метод см. self.commands) ---

    def _cmd_flush(self, data: dict) -> dict:
        """Принудительный семпл+запись прямо сейчас (вне таймера)."""
        written = self._sample_once()
        return {"status": "ok", "written": written, "total_written": self._total_written}

    def _cmd_get_stats(self, data: dict) -> dict:
        """Статистика стока: всего записано, листьев в кэше, путь к БД, ts последнего семпла."""
        with self._cache_lock:
            pending = len(self._cache)
        return {
            "status": "ok",
            "total_written": self._total_written,
            "pending_leaves": pending,
            "db_path": self._reg.db_path,
            "last_ts": self._last_ts,
        }

    def _cmd_purge_old(self, data: dict) -> dict:
        """Удалить строки старше retention_days (on-demand).

        retention_days=0 → no-op (ретенция выключена). Плановая ротация по
        расписанию — вне scope (отдельный /plan), здесь только ручная очистка.
        """
        raw = data.get("retention_days", self._reg.retention_days)
        try:
            days = int(raw)
        except (TypeError, ValueError):
            return {"status": "error", "error": f"retention_days должно быть int, получено {raw!r}"}
        if days <= 0 or self._sql is None:
            return {"status": "ok", "purged": 0, "note": "ретенция выключена (retention_days=0)"}
        cutoff = time.time() - days * 86400.0
        purged = self._sql.execute("DELETE FROM telemetry_snapshots WHERE ts < :cutoff", {"cutoff": cutoff})
        self._ctx.log_info(f"TelemetrySinkPlugin: purge_old удалил {purged} строк (старше {days}d)")
        return {"status": "ok", "purged": purged, "cutoff_ts": cutoff}

    @staticmethod
    def _as_float(value: object) -> float | None:
        """Привести к float, иначе None (нетоплевые/строковые значения отбрасываем)."""
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    def _build_proc_row(self, ts: float, pname: str, entry: dict[str, object]) -> TelemetrySnapshot:
        """Собрать строку телеметрии одного процесса (state-колонки + extra JSON)."""
        extra = entry.get("_extra")
        status = entry.get("status")
        return TelemetrySnapshot(
            ts=ts,
            process_name=pname,
            fps=self._as_float(entry.get("fps")),
            latency_ms=self._as_float(entry.get("latency_ms")),
            uptime_s=self._as_float(entry.get("uptime")),
            status=status if isinstance(status, str) else None,
            extra=json.dumps(extra, ensure_ascii=False) if extra else None,
        )

    def _build_system_row(self, ts: float, health: dict[str, object]) -> TelemetrySnapshot:
        """Собрать строку-сводку system: fps←avg_fps, остальное (active/broken_wires) → extra."""
        extra = {k: v for k, v in health.items() if k != "avg_fps"}
        return TelemetrySnapshot(
            ts=ts,
            process_name="system",
            fps=self._as_float(health.get("avg_fps")),
            extra=json.dumps(extra, ensure_ascii=False) if extra else None,
        )
