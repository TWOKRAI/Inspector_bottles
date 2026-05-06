"""PipelineExecutor — исполнение chain плагинов по items.

chain_queue.get() → sequential plugin.process(items) → SHM write → IPC send.
Error policy (Q7): pass-through + circuit breaker.
Routing (Q1): item["target"] override, else chain_targets.

Используется GenericProcess как LOOP worker.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable

from ..plugins.base import ProcessModulePlugin
from .frame_shm_middleware import FrameShmMiddleware


class PipelineExecutor:
    """Исполнение pipeline: chain of plugin.process() с error policy.

    Args:
        plugins: упорядоченный список processing-плагинов
        chain_targets: default routing targets (Q1)
        shm_middleware: для записи frame в SHM перед отправкой
        send_fn: callable для отправки IPC (process.send_message)
        max_consecutive_fails: порог circuit breaker (Q7)
        auto_reset_sec: время auto-reset circuit breaker
        critical_plugins: имена критических плагинов
        log_info: callback
        log_error: callback
    """

    def __init__(
        self,
        plugins: list[ProcessModulePlugin],
        chain_targets: list[str],
        shm_middleware: FrameShmMiddleware | None,
        send_fn: Callable,
        max_consecutive_fails: int = 5,
        auto_reset_sec: float = 60.0,
        critical_plugins: list[str] | None = None,
        log_info: Callable[[str], None] | None = None,
        log_error: Callable[[str], None] | None = None,
    ) -> None:
        self._plugins = plugins
        self._chain_targets = chain_targets
        self._shm = shm_middleware
        self._send = send_fn
        self._max_fails = max_consecutive_fails
        self._auto_reset_sec = auto_reset_sec
        self._critical_plugins = set(critical_plugins or [])
        self._log_info = log_info or (lambda msg: None)
        self._log_error = log_error or (lambda msg: None)

        # Circuit breaker state per plugin
        self._consecutive_fails: dict[str, int] = {}
        self._bypassed: dict[str, bool] = {}
        self._bypassed_since: dict[str, float] = {}

    def run_loop(
        self,
        chain_queue: queue.Queue,
        stop_event: threading.Event,
        pause_event: threading.Event,
    ) -> None:
        """LOOP worker: get items from queue → execute chain → send results.

        Args:
            chain_queue: очередь items от DataReceiver
            stop_event: сигнал остановки
            pause_event: сигнал паузы
        """
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            # Auto-reset circuit breakers
            self._check_auto_reset()

            try:
                items = chain_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            # [TRACE] Логируем каждый 30-й batch
            if not hasattr(self, "_trace_exec_cnt"):
                self._trace_exec_cnt = 0
            self._trace_exec_cnt += 1
            do_trace = (self._trace_exec_cnt % 30 == 1)

            if do_trace:
                self._log_info(
                    f"[TRACE] PipelineExecutor: got {len(items)} item(s) from queue, "
                    f"plugins={[p.name for p in self._plugins]}, "
                    f"targets={self._chain_targets}"
                )

            # Прогнать items через chain плагинов
            items = self._execute_chain(items)

            # Если items пустой после chain — ничего не отправляем
            if not items:
                if do_trace:
                    self._log_info("[TRACE] PipelineExecutor: chain вернул пустой список!")
                continue

            if do_trace:
                self._log_info(
                    f"[TRACE] PipelineExecutor: chain → {len(items)} item(s), "
                    f"sending to {self._chain_targets}"
                )

            # Отправить результаты по IPC
            self._send_results(items)

    def _execute_chain(self, items: list[dict]) -> list[dict]:
        """Последовательный прогон items через все processing-плагины."""
        for plugin in self._plugins:
            if not items:
                break

            # Circuit breaker — пропуск bypassed плагина
            if self._bypassed.get(plugin.name, False):
                # Критический плагин bypassed → пометить suspect
                if plugin.name in self._critical_plugins:
                    for item in items:
                        item["inspection_status"] = "suspect"
                continue

            try:
                items = plugin.process(items)
                # Успех — сбросить счётчик fails
                self._consecutive_fails[plugin.name] = 0
            except Exception as e:
                self._log_error(
                    f"PipelineExecutor: {plugin.name}.process() error: {e}"
                )
                # Error policy (Q7): pass-through + mark
                for item in items:
                    item["inspection_status"] = "not_inspected"

                # Circuit breaker
                fails = self._consecutive_fails.get(plugin.name, 0) + 1
                self._consecutive_fails[plugin.name] = fails

                if fails >= self._max_fails:
                    self._bypassed[plugin.name] = True
                    self._bypassed_since[plugin.name] = time.monotonic()
                    level = "CRITICAL" if plugin.name in self._critical_plugins else "WARNING"
                    self._log_error(
                        f"PipelineExecutor [{level}]: circuit breaker OPEN for "
                        f"'{plugin.name}' ({fails} consecutive fails)"
                    )

        return items

    def _send_results(self, items: list[dict]) -> None:
        """Отправить items по IPC. Routing: item['target'] → per-item, else chain_targets."""
        for item in items:
            # SHM write: убрать frame, записать в SHM
            if self._shm and "frame" in item:
                item = self._shm.strip_and_write(item)

            # Определить targets
            per_item_target = item.pop("target", None)
            targets = [per_item_target] if per_item_target else self._chain_targets

            # Отправить в каждый target
            for target in targets:
                msg = {
                    "target": target,
                    "type": "data",
                    "channel": "data",
                    "data": item,
                }
                self._send(target, msg)

    def _check_auto_reset(self) -> None:
        """Auto-reset bypassed плагинов после timeout."""
        now = time.monotonic()
        for name in list(self._bypassed.keys()):
            if not self._bypassed[name]:
                continue
            since = self._bypassed_since.get(name, now)
            if now - since >= self._auto_reset_sec:
                self._bypassed[name] = False
                self._consecutive_fails[name] = 0
                self._log_info(
                    f"PipelineExecutor: circuit breaker RESET for '{name}'"
                )

    def is_bypassed(self, plugin_name: str) -> bool:
        """Проверить, обходится ли плагин circuit breaker."""
        return self._bypassed.get(plugin_name, False)
