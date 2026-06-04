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
                    "subtype": "heartbeat",
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
            except Exception as exc:
                _log = getattr(self._services, "log_debug", self._services.log_info)
                _log(f"Не удалось отправить heartbeat: {exc}", module="heartbeat")
            # Ожидание с проверкой stop_event для быстрого завершения
            stop_event.wait(timeout=self._interval)

    def _publish_metrics_to_tree(self, workers: dict) -> None:
        """Опубликовать агрегат FPS/latency процесса напрямую в дерево StateStore.

        Здоровый путь телеметрии: процесс САМ репортит свои метрики через
        собственный StateProxy (``state.set`` → ProcessManager → StateStoreManager
        → GUI) — тот же проверенный канал, что и статус процесса. Минует
        центральную heartbeat-агрегацию в ProcessMonitor (хрупкий лишний участок).
        См. ``plans/telemetry-self-publish-redesign.md``.

        Агрегат уровня процесса:
          - ``processes.{name}.state.fps``        = max(``effective_hz``) по
            running-воркерам с hz > 0 (ведущий loop-воркер задаёт темп);
          - ``processes.{name}.state.latency_ms`` = max(``cycle_duration_ms``) —
            худшая (самая медленная) итерация как консервативная оценка latency.
        Нет ни одного hz > 0 → не публикуем (карточка остаётся «—», не «0»).

        Процессы без StateProxy (чисто системные) тихо пропускаются.

        Args:
            workers: снимок ``get_all_workers_status()`` (тайминг цикла на верхнем
                уровне каждого статуса).
        """
        proxy = getattr(self._services, "_state_proxy", None)
        if proxy is None or not workers:
            return

        hz_values: list[float] = []
        latency_values: list[float] = []
        for w in workers.values():
            if not isinstance(w, dict) or w.get("status") != "running":
                continue
            hz = w.get("effective_hz")
            if isinstance(hz, (int, float)) and hz > 0:
                hz_values.append(float(hz))
            lat = w.get("cycle_duration_ms")
            if isinstance(lat, (int, float)) and lat > 0:
                latency_values.append(float(lat))

        if not hz_values:
            return

        name = self._services.name
        try:
            proxy.set(f"processes.{name}.state.fps", round(max(hz_values), 1))
            if latency_values:
                proxy.set(f"processes.{name}.state.latency_ms", round(max(latency_values), 1))
        except Exception as exc:
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log(f"Не удалось self-publish метрик в дерево: {exc}", module="heartbeat")
