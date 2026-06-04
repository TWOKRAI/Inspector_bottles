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

Минимальный slice (Task 1.1): пишется только метрика fps (одна строка на процесс).
Полный набор метрик и system-сводка — Task 1.2; команды/retention — Task 1.3.
"""

from __future__ import annotations

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

    def configure(self, ctx: PluginContext) -> None:
        """READY: register + кэш подписки + lock. SQLManager НЕ создаём (fork!)."""
        self._ctx = ctx
        self._reg = self._init_register(ctx)

        # Кэш листьев подписки: path -> value. Заполняется callback'ом, читается
        # sample-worker'ом → защищаем lock'ом (разные потоки одного процесса).
        self._cache: dict[str, object] = {}
        self._cache_lock = threading.Lock()

        # Создаются в start() после fork — здесь только объявляем.
        self._sql: SQLManager | None = None
        self._sub_id: str | None = None
        self._total_written: int = 0

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
            ctx.log_info(f"TelemetrySinkPlugin: подписка на 'processes.**' sub_id={self._sub_id}")

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
        """Периодический семпл кэша (как DatabasePlugin._flush_loop)."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            time.sleep(self._reg.sample_interval_sec)
            self._sample_once()

    def _sample_once(self) -> int:
        """Снять снимок кэша → строки TelemetrySnapshot → insert_many.

        Минимальный slice: одна строка на процесс, у которого есть
        `processes.<P>.state.fps`. Возвращает число записанных строк.
        """
        if self._sql is None:
            return 0

        # Снимок кэша под lock — дальше работаем с копией без удержания lock.
        with self._cache_lock:
            snapshot = dict(self._cache)

        ts = time.time()
        rows: list[TelemetrySnapshot] = []
        for path, value in snapshot.items():
            # Берём только листья телеметрии: processes.<P>.state.fps.
            # config.* и system.* (не health) фильтруются автоматически —
            # подписка только на processes.**, а здесь — только *.state.fps.
            parts = path.split(".")
            if len(parts) == 4 and parts[0] == "processes" and parts[2] == "state" and parts[3] == "fps":
                process_name = parts[1]
                fps = value if isinstance(value, (int, float)) else None
                rows.append(
                    TelemetrySnapshot(
                        ts=ts,
                        process_name=process_name,
                        fps=float(fps) if fps is not None else None,
                    )
                )

        # Edge case: кэш пуст / нет fps-листьев → не пишем пустую строку.
        if not rows:
            return 0

        repo = self._sql.get_repository(TelemetrySnapshot)
        repo.insert_many(rows)
        self._total_written += len(rows)
        return len(rows)
