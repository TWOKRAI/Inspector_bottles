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
from typing import Callable

from ..plugins.base import ProcessModulePlugin
from . import frame_trace
from .cycle_metrics import CycleMetricsRecorder
from .plugin_operation_step import PipelineStepNode, PluginOperationStep, SuspectTagStep
from .plugin_runner import PluginRunner
from ...chain_module import ChainRunnable, RunnableStep
from ...router_module.middleware.frame_shm_middleware import FrameShmMiddleware


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
        log_debug: Callable[[str], None] | None = None,
        node_name: str = "",
        plugin_runner: PluginRunner | None = None,
    ) -> None:
        self._plugins = plugins
        self._chain_targets = chain_targets
        # Единый шов вызова process() (pre/post-хуки → io-debug, Этап 5). Default —
        # пустой раннер без хуков (поведение идентично прямому plugin.process()).
        self._runner = plugin_runner or PluginRunner(log_error=log_error)
        # Имя процесса-узла — для frame-trace (process-спан node, transport from).
        self._node = node_name
        self._shm = shm_middleware
        self._send = send_fn
        self._max_fails = max_consecutive_fails
        self._auto_reset_sec = auto_reset_sec
        self._critical_plugins = set(critical_plugins or [])
        self._log_info = log_info or (lambda msg: None)
        self._log_error = log_error or (lambda msg: None)
        # [TRACE] per-frame диагностика → DEBUG (не флудить INFO-консоль).
        self._log_debug = log_debug or (lambda msg: None)

        # Circuit breaker state per plugin
        self._consecutive_fails: dict[str, int] = {}
        self._bypassed: dict[str, bool] = {}
        self._bypassed_since: dict[str, float] = {}

        # Мост к chain_module (C6d): один PluginOperationStep на плагин —
        # stateless-обёртка, переиспользуется между батчами (на батч аллоцируются
        # только ChainRunnable + ChainContext из живых шагов). Порядок = порядок
        # плагинов; breaker-семантика остаётся здесь (см. _execute_chain).
        self._runnable_steps: list[RunnableStep] = [
            RunnableStep(
                node=PipelineStepNode(node_id=p.name, operation_ref=p.name),
                operation=PluginOperationStep(
                    plugin=p,
                    runner=self._runner,
                    on_success=self._on_plugin_success,
                    on_fail=self._on_plugin_fail,
                ),
                on_error="skip",
            )
            for p in self._plugins
        ]
        # Шаг-заглушка на позицию критического bypassed-плагина: тегирует текущие
        # items "suspect" (см. SuspectTagStep). Stateless — один инстанс на все
        # позиции/батчи; переиспользуется в _build_active_steps.
        self._suspect_step = RunnableStep(
            node=PipelineStepNode(node_id="suspect", operation_ref="suspect"),
            operation=SuspectTagStep(),
            on_error="skip",
        )
        # Мемоизация активных шагов: пересборка ТОЛЬКО при смене breaker-состояния
        # (две точки мутации: _on_plugin_fail открывает bypass, _check_auto_reset
        # сбрасывает). В стабильном окне (сотни батчей) переиспользуем один
        # ChainRunnable — happy-path (нет bypass) = частный случай кэша.
        self._active_runnable: ChainRunnable = ChainRunnable(self._build_active_steps())
        self._steps_dirty: bool = False

        # Тайминг цикла обработки для телеметрии GUI. Воркер queue-driven:
        # меряем только итерации с реальной работой (получен batch), а не
        # холостые spin'ы при пустой очереди — иначе effective_hz отражал бы
        # частоту опроса, а не пропускную способность обработки.
        # target_interval=0: воркер не throttle'ится, частота диктуется потоком.
        self._cycle_metrics = CycleMetricsRecorder(target_interval_s=0.0)

        # Очередь для bound-метода run() (worker target). Биндится через
        # bind_queue() — нужно, чтобы target воркера был bound-методом инстанса
        # (а не lambda): иначе WorkerManager.get_worker_status не находит
        # get_cycle_metrics через target.__self__ и FPS/latency не доедут до GUI.
        self._chain_queue: queue.Queue | None = None

    def bind_queue(self, chain_queue: queue.Queue) -> None:
        """Привязать входную очередь для bound-метода run() (worker target)."""
        self._chain_queue = chain_queue

    def run(self, stop_event: threading.Event, pause_event: threading.Event) -> None:
        """Worker target (bound-метод инстанса → get_cycle_metrics подхватывается).

        Требует предварительного bind_queue(). Делегирует в run_loop().
        """
        if self._chain_queue is None:
            raise RuntimeError("PipelineExecutor.run() вызван без bind_queue() — очередь не привязана")
        self.run_loop(self._chain_queue, stop_event, pause_event)

    def get_cycle_metrics(self) -> dict:
        """Снимок тайминга цикла обработки (потокобезопасно).

        WorkerManager.get_worker_status подмешивает результат в статус воркера →
        heartbeat → ProcessMonitor.state.fps/latency_ms → GUI. Отражает только
        итерации с реальной обработкой batch'а (см. CycleMetricsRecorder в __init__).
        """
        return self._cycle_metrics.get_cycle_metrics()

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

            # Тайминг полезной итерации (chain-обработка + send), без учёта
            # ожидания на пустой очереди. perf_counter (не monotonic): работа
            # subмиллисекундная, а monotonic на Windows имеет ~15мс гранулярность.
            t_start = time.perf_counter()

            # [TRACE] Логируем каждый 30-й batch
            if not hasattr(self, "_trace_exec_cnt"):
                self._trace_exec_cnt = 0
            self._trace_exec_cnt += 1
            do_trace = self._trace_exec_cnt % 30 == 1

            if do_trace:
                self._log_debug(
                    f"[TRACE] PipelineExecutor: got {len(items)} item(s) from queue, "
                    f"plugins={[p.name for p in self._plugins]}, "
                    f"targets={self._chain_targets}"
                )

            # Прогнать items через chain плагинов
            items = self._execute_chain(items)

            # Если items пустой после chain — ничего не отправляем
            if not items:
                if do_trace:
                    self._log_debug("[TRACE] PipelineExecutor: chain вернул пустой список!")
                self._cycle_metrics.record(time.perf_counter() - t_start)
                continue

            if do_trace:
                self._log_debug(
                    f"[TRACE] PipelineExecutor: chain → {len(items)} item(s), sending to {self._chain_targets}"
                )

            # Отправить результаты по IPC
            self._send_results(items)

            # Полный цикл обработки batch'а (chain + send) → телеметрия.
            self._cycle_metrics.record(time.perf_counter() - t_start)

    def _execute_chain(self, items: list[dict]) -> list[dict]:
        """Прогон items через processing-плагины поверх ``ChainRunnable`` (C6d).

        Механика (дизайн §5(d) инкремент 1):
          - breaker-семантика (consecutive_fails/bypass/auto_reset/critical→suspect)
            остаётся ЗДЕСЬ, вне chain_module;
          - шаги строятся по breaker-состоянию (``_build_active_steps``): живые
            плагины + ``SuspectTagStep`` на позициях критических bypassed;
          - ошибку плагина ловит ``PluginOperationStep`` (тег not_inspected +
            ``_on_plugin_fail``-репорт), ``on_error`` шага всегда ``skip`` —
            ``apply_on_error_policy`` chain_module не задействуется.

        Единый вызов ``ChainRunnable.execute`` прогоняет ВСЮ цепочку живых плагинов
        внутри одного воркера, без IPC между звеньями (бюджет границ процесса,
        перф-ревью 2026-07-12): ``_send_results`` вызывается вызывающим ПОСЛЕ, один раз.
        """
        # ChainRunnable — sequential-движок: current_frame стартует как items,
        # каждый шаг возвращает новые items (замена выхода). Пустой батч на входе
        # или после шага → следующие шаги no-op (см. PluginOperationStep).
        if self._steps_dirty:
            self._active_runnable = ChainRunnable(self._build_active_steps())
            self._steps_dirty = False
        result = self._active_runnable.execute(items, None)
        return result.frame

    def _build_active_steps(self) -> list[RunnableStep]:
        """Шаги chain на текущем breaker-состоянии, в порядке плагинов.

        Позиционная семантика suspect (breaker остаётся вне chain_module):
          - живой (не bypassed) плагин → его ``PluginOperationStep``;
          - критический bypassed → ``SuspectTagStep`` НА ЕГО ПОЗИЦИИ (тегирует items,
            существующие в этот момент прохода, — не выбрасывается из цепочки, иначе
            downstream-плагин или замена списка потеряли бы тег);
          - некритический bypassed → пропуск (просто нет шага).
        """
        steps: list[RunnableStep] = []
        for plugin, step in zip(self._plugins, self._runnable_steps):
            if not self._bypassed.get(plugin.name, False):
                steps.append(step)
            elif plugin.name in self._critical_plugins:
                steps.append(self._suspect_step)
        return steps

    def _on_plugin_success(self, plugin_name: str) -> None:
        """Успешный вызов плагина — сбросить счётчик consecutive fails (breaker)."""
        self._consecutive_fails[plugin_name] = 0

    def _on_plugin_fail(self, plugin_name: str, exc: Exception) -> None:
        """Фейл плагина — инкремент счётчика, открыть breaker при достижении порога.

        Тег ``inspection_status="not_inspected"`` ставит сам ``PluginOperationStep``
        (адаптер); лог фейла — здесь, единым каналом (см. LOW-фикс ревью).
        """
        self._log_error(f"PipelineExecutor: {plugin_name}.process() error: {exc}")
        fails = self._consecutive_fails.get(plugin_name, 0) + 1
        self._consecutive_fails[plugin_name] = fails

        if fails >= self._max_fails:
            self._bypassed[plugin_name] = True
            self._bypassed_since[plugin_name] = time.monotonic()
            self._steps_dirty = True  # breaker открылся → пересобрать шаги
            level = "CRITICAL" if plugin_name in self._critical_plugins else "WARNING"
            self._log_error(
                f"PipelineExecutor [{level}]: circuit breaker OPEN for '{plugin_name}' ({fails} consecutive fails)"
            )

    def _send_results(self, items: list[dict]) -> None:
        """Отправить items по IPC. Routing: item['target'] → per-item, else chain_targets."""
        for item in items:
            # P3.1.2: SHM-write (Claim Check) больше НЕ зовётся здесь явно — frame
            # едет в msg["data"] и выносится в SHM router-send-middleware
            # (FrameShmMiddleware.strip_data_frame_on_send, регистрируется в GenericProcess).
            # Определить targets
            per_item_target = item.pop("target", None)
            targets = [per_item_target] if per_item_target else self._chain_targets

            # data_type для корреляции в JoinInspectorManager: кадровый выход плагина
            # (напр. детектор шлёт frame в overlay_draw) помечаем "frame", если плагин
            # не задал свой data_type (line_filter ставит "overlay" — уважаем setdefault).
            if "frame" in item:
                item.setdefault("data_type", "frame")

            # frame-trace: отметить отправителя/время → receiver посчитает transport.
            frame_trace.stamp_send(item, self._node)

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
                self._steps_dirty = True  # breaker сброшен → пересобрать шаги
                self._log_info(f"PipelineExecutor: circuit breaker RESET for '{name}'")

    def is_bypassed(self, plugin_name: str) -> bool:
        """Проверить, обходится ли плагин circuit breaker."""
        return self._bypassed.get(plugin_name, False)
