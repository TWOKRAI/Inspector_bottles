# -*- coding: utf-8 -*-
"""
Управление жизненным циклом воркеров.

Поддерживает два режима выполнения:
  - ExecutionMode.LOOP — бесконечный цикл, воркер ждёт stop_event.
  - ExecutionMode.TASK — одноразовое выполнение, после завершения статус COMPLETED.
"""

import threading
import time
import traceback
from typing import Callable

from ..interfaces import IWorkerLifecycle
from ..types import WorkerStatus, ExecutionMode


class WorkerLifecycle(IWorkerLifecycle):
    """Управление жизненным циклом воркеров.

    Отвечает за создание потоков (threading.Thread), запуск, остановку, перезагрузку.
    Поддерживает два режима выполнения:
        - ExecutionMode.LOOP — бесконечный цикл, воркер ждёт stop_event.
        - ExecutionMode.TASK — одноразовое выполнение, после завершения статус COMPLETED.

    Граф состояний:
        STOPPED → [create] → CREATED (зарегистрирован, не запущен)
        CREATED → [start] → RUNNING
        RUNNING → [pause] → PAUSED
        PAUSED → [resume] → RUNNING
        RUNNING → [stop] → STOPPING → STOPPED (LOOP) или COMPLETED (TASK)
        RUNNING → [exception] → ERROR

    Основные методы:
        create_worker() — создать поток, зарегистрировать в реестре
        start_worker() — запустить поток (Thread.start())
        stop_worker() — выставить stop_event и ждать завершения
        restart_worker() — stop + start

    Внутренние методы:
        _worker_wrapper() — обёртка для потока, обрабатывает события, ошибки, метрики
        _auto_restart() — логика перезапуска при ошибке

    Thread-safety:
        Работает с WorkerRegistry (потокобезопасен) и threading.Thread (потокобезопасен).
        Решение «стартовать ли поток» и подмена потока в реестре идут под
        self._start_lock (ADR-WRK-007): start_worker, _restart_worker_internal
        и короткий снимок в stop_worker. Порядок замков единственный:
        _start_lock → registry._lock. Под _start_lock нет join, sleep, вызова
        target и логирования.
    """

    def __init__(self, manager):
        self.manager = manager
        # Простой Lock, не RLock: вложенных захватов нет, а RLock скрыл бы
        # случайную вложенность (ADR-WRK-007).
        self._start_lock = threading.Lock()

    # ---- Создание ----

    def create_worker(
        self,
        worker_name: str,
        target: Callable,
        config,
        auto_start: bool = False,
    ) -> bool:
        """Создать воркер и опционально запустить его."""
        if self.manager._worker_registry.has(worker_name):
            return False

        for dep in config.dependencies:
            if not self.manager._worker_registry.has(dep):
                return False
            if auto_start and not self.manager.is_worker_running(dep):
                return False

        stop_event = threading.Event()
        pause_event = threading.Event()

        thread = threading.Thread(
            name=f"{self.manager.manager_name}_{worker_name}",
            target=self._worker_wrapper,
            args=(worker_name, target, stop_event, pause_event),
            daemon=True,
        )

        success = self.manager._worker_registry.register(worker_name, target, config, thread, stop_event, pause_event)
        if not success:
            return False

        if auto_start:
            return self.start_worker(worker_name)
        return True

    # ---- Запуск ----

    def start_worker(self, worker_name: str) -> bool:
        """Запустить воркер — честно по таблице A/B/C (C-91, ADR-WRK-007).

        Состояние читается под self._start_lock (T — поток из реестра, E — его stop_event):
          A. T жив, статус RUNNING, E не взведён → True, нового потока нет (идемпотентно).
          B. T жив, иначе (STOPPING; RUNNING при взведённом E; ERROR в окне
             авто-рестарта; COMPLETED/STOPPED, пока обёртка дорабатывает finally) →
             False, нового потока над живым нет, предупреждение в лог. Повторить вызов позже.
          C. T не жив (не запускался, завершился, залипший статус) → новый поток
             с тем же именем, свежие события, статус RUNNING → True. Если
             Thread.start() бросил — реестр возвращён как был, исключение проброшено.
        """
        registry = self.manager._worker_registry
        with self._start_lock:
            worker_info = registry.get(worker_name)
            if not worker_info:
                return False

            if not worker_info["thread"].is_alive():
                # C: мёртвый поток → всегда новый, даже при залипшем статусе RUNNING.
                self._spawn_thread_locked(worker_name, worker_info, count_restart=True)
                return True

            status = worker_info["status"]
            if status == WorkerStatus.RUNNING and not worker_info["stop_event"].is_set():
                return True  # A

        # B: лог — вне замка; в тексте только имя воркера и статус.
        status_text = getattr(status, "value", status)
        self.manager._log_warning(
            f"старт воркера '{worker_name}' отклонён: прежний поток ещё жив (статус {status_text})"
        )
        return False

    def _spawn_thread_locked(self, worker_name: str, worker_info: dict, count_restart: bool) -> None:
        """Создать и запустить новый поток воркера. Вызывать только под self._start_lock.

        Имя потока f"{manager_name}_{worker_name}" — на нём держится
        ExecutorManager.is_executor_thread (ADR-WRK-006).
        count_restart=True — старт по start_worker: restart_count растёт, если воркер
        уже запускался; авто-рестарт считает restart_count сам (в _worker_wrapper).
        Если Thread.start() бросил — поля реестра и статус возвращены, исключение проброшено.
        """
        registry = self.manager._worker_registry
        saved = {
            key: worker_info[key]
            for key in ("thread", "stop_event", "pause_event", "restart_count", "has_been_started")
        }
        saved_status = worker_info["status"]

        stop_event = threading.Event()
        pause_event = threading.Event()
        thread = threading.Thread(
            name=f"{self.manager.manager_name}_{worker_name}",
            target=self._worker_wrapper,
            args=(worker_name, worker_info["target"], stop_event, pause_event),
            daemon=True,
        )
        worker_info["thread"] = thread
        worker_info["stop_event"] = stop_event
        worker_info["pause_event"] = pause_event
        if count_restart and worker_info["has_been_started"]:
            worker_info["restart_count"] += 1
        worker_info["has_been_started"] = True
        registry.update_status(worker_name, WorkerStatus.RUNNING)

        try:
            thread.start()
        except BaseException:
            worker_info.update(saved)
            registry.update_status(worker_name, saved_status)
            raise

    # ---- Остановка ----

    def stop_worker(self, worker_name: str, timeout: float = 5.0) -> bool:
        """Остановить воркер, дождавшись завершения потока (с таймаутом).

        Возвращает True, только если поток ДЕЙСТВИТЕЛЬНО завершился (или никогда
        не был запущен) — это честный сигнал для remove_worker/restart_worker:
        можно снимать воркер с реестра или стартовать новый поток поверх.
        Если join истёк таймаутом, а поток всё ещё жив (завис, например, в
        блокирующем cv2.read на 5-30с) — статус НЕ переводится в STOPPED
        (остаётся STOPPING), возвращается False. Раньше метод безусловно
        возвращал True и ставил STOPPED даже для зависшего потока — система
        считала воркер остановленным, хотя тред был жив (docs/audits/2026-07-20_bug-hunt.md, H-1).

        Запрос остановки не теряется авто-рестартом (C-91, ADR-WRK-007): снимок
        (поток, stop_event), статус STOPPING и stop_event.set() делаются одним шагом
        под self._start_lock — тем же замком, под которым _restart_worker_internal
        сверяет stop_event. join — снаружи замка. После join — страховка: если в
        реестре уже другой живой поток, взвести его stop_event и ждать его в
        пределах остатка timeout, пока поток в реестре не перестанет меняться.
        """
        registry = self.manager._worker_registry
        with self._start_lock:
            worker_info = registry.get(worker_name)
            if not worker_info:
                return False
            # Единый снимок (T, E) под замком: между чтениями поток в реестре не
            # подменится (H-1, п.3; C-91 H2).
            thread = worker_info["thread"]
            registry.update_status(worker_name, WorkerStatus.STOPPING)
            worker_info["stop_event"].set()

        deadline = time.monotonic() + timeout
        try:
            if thread.is_alive():
                thread.join(timeout=timeout)
        except RuntimeError:
            # join невозможен (поток не запущен или stop_worker вызван из самого
            # потока воркера) — ждать нечего: считаем воркер остановленным.
            registry.update_status(worker_name, WorkerStatus.STOPPED)
            return True

        # Страховка: авто-рестарт мог подменить поток до снимка (T2 мог дать T3).
        while not thread.is_alive():
            with self._start_lock:
                current = worker_info["thread"]
                if current is thread or not current.is_alive():
                    break
                current_stop_event = worker_info["stop_event"]
                registry.update_status(worker_name, WorkerStatus.STOPPING)
                current_stop_event.set()
            thread = current
            remaining = deadline - time.monotonic()
            if remaining > 0:
                thread.join(timeout=remaining)

        if thread.is_alive():
            # Таймаут истёк, поток всё ещё жив — не врём реестру про STOPPED.
            self.manager._log_error(
                f"Worker '{worker_name}' не остановился за {timeout}с (таймаут join) — "
                f"поток всё ещё жив, статус оставлен STOPPING"
            )
            return False

        registry.update_status(worker_name, WorkerStatus.STOPPED)
        return True

    # ---- Перезапуск ----

    def restart_worker(self, worker_name: str, timeout: float = 5.0) -> bool:
        """Остановить и запустить воркер заново.

        Если stop_worker вернул False (поток завис и не остановился за timeout) —
        НЕ стартуем новый поток поверх живого старого: иначе два треда работают на
        одном плагине (для source-воркера — два писателя в одно SHM-кольцо), см.
        H-1 п.3 аудита bug-hunt. Раньше результат stop_worker игнорировался.
        """
        if not self.manager._worker_registry.has(worker_name):
            return False

        worker_info = self.manager._worker_registry.get(worker_name)
        if worker_info and worker_info["status"] == WorkerStatus.RUNNING:
            if not self.stop_worker(worker_name, timeout):
                return False

        return self.start_worker(worker_name)

    # ---- Обёртка потока ----

    def _worker_wrapper(
        self,
        worker_name: str,
        target: Callable,
        stop_event: threading.Event,
        pause_event: threading.Event,
    ):
        """Обёртка выполнения целевой функции воркера.

        Обрабатывает ошибки, обновляет метрики и реализует автоперезапуск.
        Для ExecutionMode.TASK устанавливает статус COMPLETED вместо STOPPED.
        """
        worker_info = self.manager._worker_registry.get(worker_name)
        if not worker_info:
            return

        start_time = time.time()
        worker_info["start_time"] = start_time

        should_restart = False

        try:
            self.manager._worker_registry.update_status(worker_name, WorkerStatus.RUNNING)
            target(stop_event, pause_event)
            worker_info["successful_runs"] += 1

            # Одноразовая задача завершилась успешно
            if worker_info.get("execution_mode") == ExecutionMode.TASK:
                self.manager._worker_registry.update_status(worker_name, WorkerStatus.COMPLETED)

        except Exception as e:
            self.manager._worker_registry.update_status(worker_name, WorkerStatus.ERROR)
            worker_info["last_error"] = str(e)
            worker_info["failed_runs"] += 1

            self.manager._log_error(f"Worker '{worker_name}' error: {e}")
            traceback.print_exc()

            config = worker_info["config"]
            if config.restart_on_failure:
                if worker_info["restart_count"] < config.max_restarts:
                    should_restart = True
                    worker_info["restart_count"] += 1

        finally:
            end_time = time.time()
            run_duration = end_time - start_time
            worker_info["last_run_duration"] = run_duration
            worker_info["total_runtime"] += run_duration

            if should_restart:
                time.sleep(0.1)
                # stop_event умирающего потока: если остановку уже запросили,
                # _restart_worker_internal отменит рестарт (C-91 H2). Вызов через
                # экземплярный атрибут — тесты подменяют его.
                self._restart_worker_internal(worker_name, stop_event)
            else:
                current_status = self.manager._worker_registry.get_status(worker_name)
                # Не перезаписываем COMPLETED и ERROR (при превышении лимита перезапусков)
                if current_status not in (WorkerStatus.ERROR, WorkerStatus.COMPLETED):
                    self.manager._worker_registry.update_status(worker_name, WorkerStatus.STOPPED)

    def _restart_worker_internal(self, worker_name: str, stop_event: threading.Event) -> bool:
        """Внутренний перезапуск после ошибки (вызывается из потока воркера).

        stop_event — событие остановки умирающего потока. Его сверяют под
        self._start_lock, тем же замком, под которым stop_worker взводит его:
        если остановку уже запросили, рестарт отменяется, статус STOPPED,
        возврат False. Запрос остановки не теряется (C-91 H2, ADR-WRK-007).
        """
        registry = self.manager._worker_registry
        with self._start_lock:
            worker_info = registry.get(worker_name)
            if not worker_info:
                return False
            cancelled = stop_event.is_set()
            if cancelled:
                registry.update_status(worker_name, WorkerStatus.STOPPED)
            else:
                self._spawn_thread_locked(worker_name, worker_info, count_restart=False)

        if cancelled:
            self.manager._log_info(f"авто-рестарт воркера '{worker_name}' отменён: запрошена остановка")
            return False
        return True
