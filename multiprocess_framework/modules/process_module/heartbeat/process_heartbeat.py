"""ProcessHeartbeat — отправка периодических heartbeat-сообщений ProcessManager-у."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class ProcessHeartbeat:
    """Heartbeat sender через IProcessServices.

    Отправляет периодические heartbeat-сообщения в ProcessManager
    для мониторинга состояния процесса.
    """

    def __init__(self, services: Any) -> None:
        """
        Args:
            services: объект удовлетворяющий IProcessServices
        """
        self._services = services
        self._interval: float = 5.0

    def start(self) -> None:
        """Создать и запустить heartbeat воркер если включён в конфиге."""
        interval = self._services.get_config("heartbeat_interval", 5.0)
        try:
            interval = float(interval)
        except (TypeError, ValueError):
            interval = 5.0

        if interval <= 0:
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log("Heartbeat отключён (heartbeat_interval <= 0)", module="heartbeat")
            return

        if not self._services.worker_manager:
            return

        from ...worker_module import ThreadConfig, ThreadPriority

        self._interval = interval
        self._services.worker_manager.create_worker(
            "heartbeat_sender",
            self._loop,
            ThreadConfig(priority=ThreadPriority.BACKGROUND),
            auto_start=True,
        )
        _log = getattr(self._services, "log_debug", self._services.log_info)
        _log(
            f"Heartbeat воркер запущен (interval={interval}с)",
            module="heartbeat",
        )

    def _loop(self, stop_event, pause_event) -> None:
        """Цикл отправки heartbeat-сообщений."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            try:
                heartbeat_msg = {
                    "type": "system",
                    "command": "heartbeat",
                    "sender": self._services.name,
                    "timestamp": time.time(),
                    "status": getattr(self._services, "_current_process_status", "running"),
                }
                # Данные о воркерах для ProcessMonitor
                # Dict at Boundary: get_all_workers_status() уже возвращает чистые dict
                workers: dict = {}
                if self._services.worker_manager:
                    get_status = getattr(self._services.worker_manager, "get_all_workers_status", None)
                    if get_status is not None:
                        try:
                            workers = get_status()
                            # Исключаем metrics для экономии трафика IPC. Тайминг цикла
                            # (effective_hz / cycle_duration_ms) подмешан на ВЕРХНИЙ
                            # уровень статуса воркера — НЕ внутри metrics — и сохраняется.
                            for w in workers.values():
                                if isinstance(w, dict):
                                    w.pop("metrics", None)
                            heartbeat_msg["workers_status"] = workers
                        except Exception:
                            workers = {}
                self._services.send_message("ProcessManager", heartbeat_msg)

                # Self-publish метрик процесса напрямую в дерево StateStore.
                # Здоровый путь телеметрии — тот же канал, что и статус процесса.
                self._publish_metrics_to_tree(workers)

                # Self-publish здоровья процесса (Ф2 Task 2.1) — тот же канал.
                # Отдельно от метрик: health публикуется даже без воркеров и только
                # при изменениях (take_dirty) — естественный rate-limit на такт HB.
                self._publish_health_to_tree()

                # Дренаж ObservabilityHub процесса (Ф5.16): log/stats-буфер hub'а
                # → реальные менеджеры адаптером. error/critical идут мимо буфера
                # (write-through), здесь их нет. Прецедент — health self-publish 2.1.
                self._drain_observability()
            except Exception as exc:
                _log = getattr(self._services, "log_debug", self._services.log_info)
                _log(f"Не удалось отправить heartbeat: {exc}", module="heartbeat")
            # Ожидание с проверкой stop_event для быстрого завершения
            stop_event.wait(timeout=self._interval)

    def _drain_observability(self) -> None:
        """Ф5.16: слить log/stats-буфер ObservabilityHub процесса в реальные
        менеджеры по такту heartbeat. Процессы без hub'а тихо пропускаются;
        исключения глушим — дренаж телеметрии не критичен для такта HB."""
        hub = getattr(self._services, "_observability_hub", None)
        drain = getattr(self._services, "_observability_drain", None)
        if hub is None or drain is None:
            return
        store = getattr(self._services, "_observability_store", None)
        from ..managers.observability_wiring import drain_process_observability

        try:
            drain_process_observability(hub, drain, store)
        except Exception as exc:  # noqa: BLE001 — телеметрия не критична
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log(f"Не удалось слить observability-буфер: {exc}", module="heartbeat")

    def _publish_metrics_to_tree(self, workers: dict) -> None:
        """Опубликовать телеметрию процесса и каждого воркера в дерево StateStore.

        Здоровый путь телеметрии: процесс САМ репортит свои метрики через
        собственный StateProxy (``state.set`` → ProcessManager → StateStoreManager
        → GUI) — тот же проверенный канал, что и статус процесса. Минует
        центральную heartbeat-агрегацию в ProcessMonitor (хрупкий лишний участок).
        См. ``plans/telemetry-self-publish-redesign.md``.

        Per-worker (строки таблицы воркеров в детальном виде процесса):
          - ``processes.{name}.workers.{w}.status``            — живой статус;
          - ``processes.{name}.workers.{w}.effective_hz``      — частота воркера;
          - ``processes.{name}.workers.{w}.cycle_duration_ms`` — время цикла (latency).

        Агрегат уровня процесса (карточка):
          - ``processes.{name}.state.fps``        = max(``effective_hz``) по
            running-воркерам с hz > 0 (ведущий loop-воркер задаёт темп);
          - ``processes.{name}.state.latency_ms`` = max(``cycle_duration_ms``) —
            время самого медленного воркера (узкое горло процесса).
        Нет ни одного hz > 0 → агрегат не публикуем (карточка остаётся «—»).

        Процессы без StateProxy (чисто системные) тихо пропускаются.

        Args:
            workers: снимок ``get_all_workers_status()`` (тайминг цикла на верхнем
                уровне каждого статуса).
        """
        proxy = getattr(self._services, "_state_proxy", None)
        if proxy is None or not workers:
            return

        # E6/Task 5.7: собрать все листья (per-worker + агрегат) в один вложенный
        # payload и отправить ОДНИМ proxy.merge вместо 3W+2 proxy.set — глубокий
        # merge сохраняет сиблинги (health.* и пр.), число сообщений ↓ ~в W раз.
        from .telemetry import build_worker_telemetry

        result = build_worker_telemetry(workers, self._services.name)
        if result is None:
            return
        path, data = result
        try:
            proxy.merge(path, data)
        except Exception as exc:
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log(f"Не удалось self-publish метрик процесса: {exc}", module="heartbeat")

    def _publish_health_to_tree(self) -> None:
        """Опубликовать здоровье процесса (Ф2 Task 2.1) в дерево StateStore.

        Тот же self-publish канал, что и телеметрия: процесс сам репортит своё
        здоровье через ``_state_proxy`` (``processes.<name>.health.*``). Публикатор
        (``health.publish_health``) снимает грязный снапшот единого HealthState
        процесса и шлёт только при изменениях — публикация вырождается в no-op,
        пока никто не звал report_error/set_status. Процессы без StateProxy или без
        HealthState (никто ещё не трогал health) тихо пропускаются.
        """
        proxy = getattr(self._services, "_state_proxy", None)
        if proxy is None:
            return
        state = getattr(self._services, "_health_state", None)
        if state is None:
            return

        from ..health import publish_health

        try:
            # Task 2.2: пассивный шаг восстановления breaker по тишине — на такте
            # heartbeat, до публикации (переход open→half_open→closed попадёт в снапшот).
            poll = getattr(state, "poll", None)
            if callable(poll):
                poll()
            publish_health(state, proxy, self._services.name)
        except Exception as exc:  # noqa: BLE001 — health не критичен для работы процесса
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log(f"Не удалось self-publish health процесса: {exc}", module="heartbeat")
