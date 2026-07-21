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
    """

    def __init__(self, manager):
        self.manager = manager

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
        """Запустить воркер. Создаёт новый поток если предыдущий завершился."""
        worker_info = self.manager._worker_registry.get(worker_name)
        if not worker_info:
            return False

        if worker_info["status"] == WorkerStatus.RUNNING:
            return True

        if not worker_info["thread"].is_alive():
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

            if worker_info["has_been_started"]:
                worker_info["restart_count"] += 1
            worker_info["has_been_started"] = True

            worker_info["stop_event"].clear()
            worker_info["pause_event"].clear()
            self.manager._worker_registry.update_status(worker_name, WorkerStatus.RUNNING)
            worker_info["thread"].start()

        return True

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
        """
        worker_info = self.manager._worker_registry.get(worker_name)
        if not worker_info:
            return False

        self.manager._worker_registry.update_status(worker_name, WorkerStatus.STOPPING)
        worker_info["stop_event"].set()

        # Единое чтение thread в локальную переменную вместо двух обращений к
        # worker_info["thread"] (было :137 is_alive, :138 join) — устраняет TOCTOU-гонку:
        # между двумя чтениями _restart_worker_internal мог подменить объект в реестре
        # на новый несстартованный Thread → join() на нём бросает RuntimeError (H-1, п.3).
        thread = worker_info["thread"]

        try:
            if thread.is_alive():
                thread.join(timeout=timeout)
        except RuntimeError:
            # Поток ещё не был запущен (start() не вызван) — join невозможен,
            # но и останавливать нечего: считаем воркер остановленным.
            self.manager._worker_registry.update_status(worker_name, WorkerStatus.STOPPED)
            return True

        if thread.is_alive():
            # Таймаут истёк, поток всё ещё жив — не врём реестру про STOPPED.
            self.manager._log_error(
                f"Worker '{worker_name}' не остановился за {timeout}с (таймаут join) — "
                f"поток всё ещё жив, статус оставлен STOPPING"
            )
            return False

        self.manager._worker_registry.update_status(worker_name, WorkerStatus.STOPPED)
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
                self._restart_worker_internal(worker_name)
            else:
                current_status = self.manager._worker_registry.get_status(worker_name)
                # Не перезаписываем COMPLETED и ERROR (при превышении лимита перезапусков)
                if current_status not in (WorkerStatus.ERROR, WorkerStatus.COMPLETED):
                    self.manager._worker_registry.update_status(worker_name, WorkerStatus.STOPPED)

    def _restart_worker_internal(self, worker_name: str) -> bool:
        """Внутренний перезапуск после ошибки (вызывается из потока воркера)."""
        worker_info = self.manager._worker_registry.get(worker_name)
        if not worker_info:
            return False

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

        worker_info["stop_event"].clear()
        worker_info["pause_event"].clear()
        self.manager._worker_registry.update_status(worker_name, WorkerStatus.RUNNING)
        worker_info["has_been_started"] = True
        worker_info["thread"].start()
        return True
