# -*- coding: utf-8 -*-
"""
Типы и перечисления worker_module.

Единственный источник правды для всех типов модуля.
"""

import threading
from enum import Enum
from typing import Callable, Dict, List, Optional, TYPE_CHECKING

try:
    from typing import TypedDict
except ImportError:
    from typing_extensions import TypedDict

if TYPE_CHECKING:
    from ..core.thread_config import ThreadConfig


class WorkerStatus(Enum):
    """Статусы состояния воркера.

    STOPPED: Воркер остановлен. Типичный финальный статус для LOOP-режима.
    RUNNING: Воркер в данный момент выполняется.
    ERROR: Воркер выбросил исключение и не перезапускается (max_restarts исчерпаны).
    STOPPING: Промежуточный статус во время завершения (редко виден).
    COMPLETED: Воркер успешно завершился. Финальный статус для TASK-режима.
    """
    STOPPED = "stopped"
    RUNNING = "running"
    ERROR = "error"
    STOPPING = "stopping"
    COMPLETED = "completed"   # для одноразовых задач (ExecutionMode.TASK)


class ThreadPriority(Enum):
    """Приоритеты потоков выполнения.

    Приоритет влияет на poll_interval для проверки stop_event и pause_event в цикле.
    Позволяет баланс между отзывчивостью и нагрузкой на CPU.

    SYSTEM: 0.001s (1ms)
        Для критичных системных потоков фреймворка (message_processor).
        Очень частая проверка, может нагружать CPU при большом кол-во потоков.

    REALTIME: 0.01s (10ms)
        Для потоков, требующих низкой задержки (реал-тайм обработка).

    NORMAL: 0.1s (100ms)
        Стандартный приоритет для пользовательских воркеров (по умолчанию).
        Хороший баланс между отзывчивостью и нагрузкой.

    BATCH: 1.0s
        Для фоновой пакетной обработки (большие парти, очередь обработки).
        Редко проверяется, низкая нагрузка на CPU.

    BACKGROUND: 5.0s
        Для низкоприоритетных фоновых задач.
        Очень редко проверяется.
    """
    SYSTEM = 0        # 0.001s интервал — системные потоки
    REALTIME = 1      # 0.01s  интервал — реальное время
    NORMAL = 2        # 0.1s   интервал — обычные
    BATCH = 3         # 1.0s   интервал — пакетная обработка
    BACKGROUND = 4    # 5.0s   интервал — фоновые


class WorkerType(Enum):
    """Категории потоков по назначению.

    SYSTEM: Воркеры внутреннего механизма фреймворка.
        Примеры: message_processor, health_check, stats_collector (будущее).
        Создаются автоматически при инициализации ProcessModule.
        Обычно высокий приоритет (SYSTEM, REALTIME).

    APPLICATION: Пользовательские задачи.
        Примеры: worker_1, data_processor, sensor_reader.
        Создаются из конфига процесса или программно.
        Обычно средний/низкий приоритет (NORMAL, BATCH, BACKGROUND).
    """
    SYSTEM = "system"           # Внутренний механизм фреймворка
    APPLICATION = "application" # Пользовательские задачи


class ExecutionMode(Enum):
    """Режим выполнения воркера.

    LOOP: Бесконечный цикл.
        Воркер вызывает run(stop_event, pause_event) и ожидает выхода из цикла.
        Типичный цикл:
            while not stop_event.is_set():
                if pause_event.is_set():
                    time.sleep(0.05)
                    continue
                do_work()
                time.sleep(poll_interval)

        Финальный статус: STOPPED (при stop_worker()) или ERROR (при исключении).
        Примеры: постоянная обработка данных, опрос сенсоров, обработка очередей.

    TASK: Одноразовое выполнение.
        Воркер вызывает run(stop_event, pause_event) один раз и завершается.
        Функция выполняется от начала до конца, не требует бесконечного цикла.

        Финальный статус: COMPLETED (при успешном завершении) или ERROR (при исключении).
        Примеры: инициализация БД, миграция данных, загрузка конфига, отчёт.

    Note:
        LOOP режим идеален для постоянных услуг внутри процесса.
        TASK режим идеален для инициализирующих задач, которые должны выполниться один раз.
    """
    LOOP = "loop"   # Циклический: run() с бесконечным циклом, слушает stop_event
    TASK = "task"   # Одноразовый: run() выполняется один раз и завершается


class WorkerInfo(TypedDict):
    """Полная информация о зарегистрированном воркере.

    Это словарь со всеми данными о воркере, хранящийся в WorkerRegistry.

    thread: threading.Thread
        OS thread object. Используется для проверки is_alive() и join().

    stop_event: threading.Event
        Событие для сигнала воркеру остановиться. Потокобезопасно.
        Устанавливается в True при stop_worker() или через pause_event.

    pause_event: threading.Event
        Событие для паузы воркера. Работает только в LOOP режиме.
        Если установлено, воркер ждёт в цикле без выполнения работы.

    target: Callable
        Функция-воркер с сигнатурой run(stop_event, pause_event).

    config: ThreadConfig
        Конфигурация потока (приоритет, restart_on_failure, max_restarts и т.д.).

    status: WorkerStatus
        Текущий статус (STOPPED, RUNNING, ERROR, STOPPING, COMPLETED).

    worker_type: WorkerType
        SYSTEM (фреймворк) или APPLICATION (пользовательский).

    execution_mode: ExecutionMode
        LOOP (бесконечный) или TASK (одноразовый).

    restart_count: int
        Сколько раз воркер был перезапущен после ошибки.

    last_error: Optional[str]
        Последнее исключение (текст), если было.

    start_time: Optional[float]
        Timestamp (time.time()) последнего запуска. None до первого запуска.

    total_runtime: float
        Общее время работы в секундах (накапливается при каждом запуске).

    last_run_duration: float
        Длительность последнего цикла/задачи в секундах.

    successful_runs: int
        Для LOOP: кол-во успешных итераций цикла.
        Для TASK: 1 если успешно, 0 иначе.

    failed_runs: int
        Для LOOP: кол-во итераций, закончившихся исключением.
        Для TASK: 1 если было исключение, 0 иначе.

    has_been_started: bool
        Был ли воркер когда-либо запущен?
    """
    thread: threading.Thread
    stop_event: threading.Event
    pause_event: threading.Event
    target: Callable
    config: "ThreadConfig"
    status: WorkerStatus
    worker_type: WorkerType
    execution_mode: ExecutionMode
    restart_count: int
    last_error: Optional[str]
    start_time: Optional[float]
    total_runtime: float
    last_run_duration: float
    successful_runs: int
    failed_runs: int
    has_been_started: bool
