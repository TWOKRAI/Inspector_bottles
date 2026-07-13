"""SourceProducer — produce()-loop для source-плагинов.

plugin.produce() → FrameShmMiddleware.strip_and_write() → IPC send в chain_targets.
Smart sleep для target FPS.

Используется GenericProcess как LOOP worker.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from ..plugins.base import ProcessModulePlugin
from ..health import IHealthReporter
from . import frame_trace
from .cycle_metrics import CycleMetricsRecorder
from .plugin_runner import PluginRunner
from ...router_module.middleware.frame_shm_middleware import FrameShmMiddleware

#: Backoff (сек) при открытом produce-breaker: вместо горячего цикла ошибок на
#: мёртвом источнике спим дольше, отдавая CPU. Держим отзывчивость на stop_event
#: порциями внутри smart-sleep.
DEFAULT_BREAKER_BACKOFF_SEC = 1.0


class SourceProducer:
    """Produce-loop для source-плагинов.

    Args:
        plugin: source-плагин с методом produce()
        shm_middleware: для записи frame в SHM
        send_fn: callable для отправки IPC
        chain_targets: куда отправлять items
        target_fps: целевой FPS (для throttle)
        log_info: callback
        log_error: callback
        health: honest-репортер здоровья (Task 2.2). produce()-фейлы кормят его
            breaker (report_error), успех — record_success. None → no-op (юниты/
            обратная совместимость): поведение как раньше, только без наблюдаемости.
        breaker_backoff_sec: сон при открытом breaker (вместо target_interval).
    """

    def __init__(
        self,
        plugin: ProcessModulePlugin,
        shm_middleware: FrameShmMiddleware | None,
        send_fn: Callable,
        chain_targets: list[str],
        target_fps: float = 25.0,
        log_info: Callable[[str], None] | None = None,
        log_error: Callable[[str], None] | None = None,
        log_debug: Callable[[str], None] | None = None,
        node_name: str = "",
        plugin_runner: PluginRunner | None = None,
        health: IHealthReporter | None = None,
        breaker_backoff_sec: float = DEFAULT_BREAKER_BACKOFF_SEC,
    ) -> None:
        self._plugin = plugin
        self._shm = shm_middleware
        # Единый шов вызова produce() (pre/post-хуки → io-debug, Этап 5). Default —
        # пустой раннер без хуков (поведение идентично прямому plugin.produce()).
        self._runner = plugin_runner or PluginRunner(log_error=log_error)
        self._send = send_fn
        self._chain_targets = chain_targets
        # Имя процесса-узла — для frame-trace (transport from/to, process node).
        self._node = node_name
        self._target_interval = 1.0 / max(target_fps, 1.0)
        self._log_info = log_info or (lambda msg: None)
        self._log_error = log_error or (lambda msg: None)
        # [TRACE] per-frame диагностика → DEBUG (не флудить INFO-консоль). Дефолт —
        # общий kwargs-safe no-op (F6d, ревью 2026-07-13): вызов ниже несёт
        # trace_id=... как extra для LogRecord (Ф7 G.6) — реальные
        # ProcessModule._log_debug тоже kwargs-safe.
        self._log_debug = log_debug or frame_trace.noop_log
        # Honest produce-breaker (Task 2.2). context-тег фиксируем на источнике,
        # чтобы last_error показывал, ЧЕЙ produce() падает.
        self._health = health
        self._health_context = f"produce:{getattr(plugin, 'name', '') or 'source'}"
        self._breaker_backoff = max(0.0, float(breaker_backoff_sec))

        # Тайминг цикла (produce + send + smart-sleep) для телеметрии GUI.
        # target_interval = 1/target_fps, поэтому effective_hz ≈ фактический FPS.
        self._cycle_metrics = CycleMetricsRecorder(target_interval_s=self._target_interval)

    def get_cycle_metrics(self) -> dict:
        """Снимок тайминга цикла (потокобезопасно).

        WorkerManager.get_worker_status подмешивает результат в статус воркера →
        heartbeat → ProcessMonitor.state.fps/latency_ms → GUI.
        """
        return self._cycle_metrics.get_cycle_metrics()

    def run_loop(self, stop_event: threading.Event, pause_event: threading.Event) -> None:
        """LOOP worker: produce() → SHM write → IPC send.

        Smart sleep: вычитает время produce() из target_interval.

        КОНТРАКТ КООПЕРАТИВНОСТИ: цикл проверяет ``stop_event`` каждую итерацию,
        но НЕ может прервать блокирующий ``produce()`` извне (Python-потоки не
        прерываемы). Поэтому source-плагин ОБЯЗАН делать produce() кооперативным —
        не блокировать дольше ~2 интервалов кадра (короткий таймаут захвата, возврат
        ``[]`` при отсутствии кадра). Иначе worker не остановится за дедлайн
        ``stop_all_workers`` → ``terminate()`` (5с-лаг switch + утечка ресурса).
        """
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            t_start = time.monotonic()

            # Снимок кумулятивного счётчика ошибок ДО produce() — чтобы отличить
            # честно-успешную итерацию от той, где плагин ПРОГЛОТИЛ ошибку внутри
            # (contain→report→degrade, M-err-1/2, волна C): такой плагин ловит отказ
            # железа/соседа в своём produce(), зовёт ctx.health.report_error и
            # возвращает [] — produce() НЕ бросает, но итерация НЕ успешна.
            errors_before = self._health.error_count if self._health is not None else 0

            produce_failed = False
            try:
                # Вызов через PluginRunner — единый шов с pre/post-хуками (io-debug).
                items = self._runner.call_produce(self._plugin)
            except NotImplementedError:
                self._log_error(f"SourceProducer: {self._plugin.name} не реализует produce()")
                stop_event.set()
                return
            except Exception as e:
                self._log_error(f"SourceProducer: {self._plugin.name}.produce() error: {e}")
                items = []
                produce_failed = True
                # Honest produce-breaker (Task 2.2): кормим тот же счётчик, что и
                # плагины — N подряд produce()-фейлов откроют breaker → health degraded.
                if self._health is not None:
                    self._health.report_error(e, context=self._health_context)

            # record_success сбрасывает подряд-счётчик breaker → закрывает деградацию.
            # Зовём ТОЛЬКО если итерация честно успешна: produce() не бросил И плагин
            # не отчитался об ошибке внутри (error_count не вырос). Иначе безусловный
            # record_success «съедал» бы report_error флагман-источников
            # (capture/camera_service ловят ошибку внутри и возвращают []) —
            # breaker никогда бы не открылся, degrade не наступил (баг Ф2 prod-пути).
            if not produce_failed and self._health is not None:
                if self._health.error_count == errors_before:
                    self._health.record_success()

            # Штамп времени захвата → метаданные кадра (едут через всю цепочку как
            # item["capture_ts"]). На выходе пайплайна (дисплей) считается
            # сквозная задержка now - capture_ts. time.time() (wall) —
            # кросс-процессно сравнимо на одной машине.
            # produce-спан пишет декоратор frame_trace.traced (авто на produce()).
            # Ф7 G.6: trace_id назначается ЗДЕСЬ — единственное место рождения кадра
            # (звено 1) — до TRACE-лога ниже, чтобы он тоже мог нести trace_id.
            capture_ts = time.time()
            for item in items:
                if isinstance(item, dict):
                    item.setdefault("capture_ts", capture_ts)
                    frame_trace.ensure_trace_id(item)

            # [TRACE] Логируем каждый 30-й кадр (чтобы не спамить)
            if items and hasattr(self, "_trace_cnt"):
                self._trace_cnt += 1
            elif items:
                self._trace_cnt = 1
            if items and self._trace_cnt % 30 == 1:
                frame = items[0].get("frame")
                shape = frame.shape if frame is not None and hasattr(frame, "shape") else None
                self._log_debug(
                    f"[TRACE] SourceProducer({self._plugin.name}): "
                    f"produce() → {len(items)} item(s), frame shape={shape}, "
                    f"targets={self._chain_targets}",
                    # F6c (ревью 2026-07-13): без повторного isinstance — единственный
                    # guard живёт в ensure_trace_id (вызван строкой выше); items[0]
                    # здесь читается тем же способом, что и frame=items[0].get("frame")
                    # строкой выше (существующая конвенция файла).
                    trace_id=items[0].get("trace_id"),
                )

            # Отправить каждый item
            for item in items:
                self._send_item(item)

            # Backoff при открытом produce-breaker (Task 2.2): не жечь CPU в горячем
            # цикле ошибок на мёртвом источнике — спим breaker_backoff (обычно >>
            # интервала кадра). Иначе — обычный smart-sleep до target FPS.
            if self._health is not None and self._health.breaker_open:
                self._sleep_cooperative(self._breaker_backoff, stop_event)
            else:
                elapsed = time.monotonic() - t_start
                sleep_time = self._target_interval - elapsed
                if sleep_time > 0:
                    self._sleep_cooperative(sleep_time, stop_event)

            # Полный цикл (produce + send + sleep) → телеметрия.
            self._cycle_metrics.record(time.monotonic() - t_start)

    def _sleep_cooperative(self, sleep_time: float, stop_event: threading.Event) -> None:
        """Сон порциями с проверкой stop_event (отзывчивость на остановку).

        max(0.0, ...) защищает от race: между проверкой while и вычислением остатка
        время может «проскочить» за deadline — без max() в time.sleep() уйдёт
        отрицательное значение → ValueError.
        """
        if sleep_time <= 0:
            return
        deadline = time.monotonic() + sleep_time
        while time.monotonic() < deadline and not stop_event.is_set():
            time.sleep(max(0.0, min(0.01, deadline - time.monotonic())))

    def _send_item(self, item: dict) -> None:
        """IPC send одного item.

        P3.1.2: SHM-write (Claim Check) больше НЕ зовётся здесь явно — frame едет
        в ``msg["data"]`` и выносится в SHM router-send-middleware
        (``FrameShmMiddleware.strip_data_frame_on_send``, регистрируется в
        GenericProcess). Producer не знает про SHM.
        """
        # Routing: item["target"] → per-item, else chain_targets
        per_item_target = item.pop("target", None)
        targets = [per_item_target] if per_item_target else self._chain_targets

        # data_type для корреляции в JoinInspectorManager: кадровые items от источника
        # помечаем "frame" (точно — только при наличии frame, чтобы не тегать heartbeat
        # и пр.). Плагин мог задать свой data_type — уважаем (setdefault).
        if "frame" in item:
            item.setdefault("data_type", "frame")

        # frame-trace: отметить отправителя/время → receiver посчитает transport.
        frame_trace.stamp_send(item, self._node)

        for target in targets:
            msg = {
                "target": target,
                "type": "data",
                "channel": "data",
                "data": item,
            }
            self._send(target, msg)
