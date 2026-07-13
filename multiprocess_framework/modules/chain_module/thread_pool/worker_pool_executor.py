"""WorkerPoolExecutor — пул параллельного исполнения шагов поверх worker_module.

C6(e): chain-параллелизм больше НЕ держит собственный поток-пул из stdlib.
Вместо этого N персистентных LOOP-воркеров создаются через ``WorkerManager``
(единый механизм потоков фреймворка) и разбирают задачи из общей
``queue.Queue``. Так у chain_module нет второго, дублирующего механизма потоков
(D2 аудита 2026-07-10).

Handle задачи — Event-based (паттерн ``PendingTask`` из ``worker_pool/dispatcher``),
интерфейсно совместим с ``concurrent.futures.Future.result(timeout=...)``: чтобы
публичный контракт ``ChainThreadPool.submit_bundle`` не менялся, вызывающий код
может как ждать каждый handle напрямую (``handle.result(timeout)``), так и
собирать пачку через ``collect_results``.

Почему обёртка, а НЕ расширение ``IWorkerManager``: единственный потребитель
submit/collect-паттерна — chain-пул. Расширять публичный контракт worker_module
(LOOP-воркеры почти в каждом процессе) ради одного узкого кейса — риск для
стабильного API. Обёртка локальна к chain_module и использует ТОЛЬКО существующий
публичный ``create_worker``/``stop_worker``/``shutdown``.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any

from ...base_manager import BaseManager, ObservableMixin
from ...worker_module import ThreadConfig, WorkerManager
from ...worker_module.types import ExecutionMode

# Периодичность опроса входной очереди воркером. Держит цикл отзывчивым к
# stop_event (проверяется между задачами), не тратя CPU на busy-wait.
_QUEUE_POLL_SEC = 0.05


class _PoolTask:
    """Задача пула: операция + payload + Event для блокирующего ожидания.

    Аналог ``concurrent.futures.Future`` в объёме, нужном chain-пулу: одна
    операция, один результат/исключение, ``result(timeout)`` для ожидания.
    Event-based (как ``PendingTask`` в WorkerPoolDispatcher) — без зависимости
    от ``concurrent.futures``.
    """

    __slots__ = ("_operation", "_payload", "_context", "_event", "_value", "_exc")

    def __init__(self, operation: Any, payload: Any, context: Any) -> None:
        self._operation = operation
        self._payload = payload
        self._context = context
        self._event = threading.Event()
        self._value: Any = None
        self._exc: BaseException | None = None

    def _run(self) -> None:
        """Исполнить операцию (вызывается воркером пула). Исключение — в слот."""
        try:
            self._value = self._operation.execute(self._payload, self._context)
        except Exception as exc:  # noqa: BLE001 — политика ошибок решается вызывающим
            self._exc = exc
        finally:
            self._event.set()

    def result(self, timeout: float | None = None) -> Any:
        """Дождаться результата. TimeoutError при истечении, иначе значение/исключение."""
        if not self._event.wait(timeout):
            raise TimeoutError(f"Task did not complete within {timeout}s")
        if self._exc is not None:
            raise self._exc
        return self._value


class WorkerPoolExecutor(BaseManager, ObservableMixin):
    """Пул параллельного исполнения шагов на персистентных LOOP-воркерах.

    N воркеров создаются в ``__init__`` (как прежний поток-пул — готов сразу,
    без отдельного ``initialize()``) и крутят ``_pool_loop``, разбирая
    задачи из общей ``queue.Queue``. ``submit_bundle`` кладёт по задаче на каждый
    шаг (каждый получает ``frame.copy()`` для thread-safety), ``collect_results``
    собирает результаты с общим бюджетом timeout.

    Args:
        max_workers: Количество LOOP-воркеров пула.
        step_timeout: Максимальное время ожидания одного шага (секунды).
        logger: LoggerManager или ObservableMixin-совместимый объект.
        worker_manager: Внешний WorkerManager (для тестов/переиспользования).
            None → создаётся собственный (дом воркеров пула локален экземпляру).
        manager_name: Имя менеджера (для именования потоков/логов).
    """

    def __init__(
        self,
        max_workers: int = 2,
        step_timeout: float = 10.0,
        logger: Any = None,
        worker_manager: WorkerManager | None = None,
        manager_name: str = "WorkerPoolExecutor",
    ) -> None:
        BaseManager.__init__(self, manager_name=manager_name)
        ObservableMixin.__init__(self, managers={"logger": logger})

        self._max_workers = max(1, max_workers)
        self._step_timeout = step_timeout
        self._lock = threading.Lock()
        self._in_queue: queue.Queue[_PoolTask] = queue.Queue()

        self._owns_manager = worker_manager is None
        self._worker_manager = worker_manager or WorkerManager(manager_name=f"{manager_name}Workers")
        self._worker_manager.initialize()

        self._worker_names: list[str] = []
        self._start_workers()

    # ------------------------------------------------------------------
    # Жизненный цикл воркеров пула
    # ------------------------------------------------------------------

    def _start_workers(self) -> None:
        """Создать и запустить ``self._max_workers`` персистентных LOOP-воркеров."""
        config = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        for i in range(self._max_workers):
            name = f"chain_pool_{i}"
            self._worker_manager.create_worker(name, self._pool_loop, config, auto_start=True)
            self._worker_names.append(name)

    def _stop_workers(self) -> None:
        """Остановить и снять с учёта все воркеры пула.

        ``remove_worker`` (не ``stop_worker``): останавливает поток И убирает из
        реестра WorkerManager. Иначе после resize имена ``chain_pool_i``
        остались бы занятыми STOPPED-воркерами и пересоздание коллизировало бы.
        """
        for name in self._worker_names:
            self._worker_manager.remove_worker(name)
        self._worker_names.clear()

    def _pool_loop(self, stop_event: threading.Event, pause_event: threading.Event) -> None:
        """Тело LOOP-воркера: разбирать задачи из очереди до stop_event.

        ``get(timeout=...)`` даёт периодическую проверку ``stop_event`` без
        busy-wait. Задача сама кладёт результат/исключение в свой Event-слот.
        """
        while not stop_event.is_set():
            try:
                task = self._in_queue.get(timeout=_QUEUE_POLL_SEC)
            except queue.Empty:
                continue
            if task is None:  # сентинел (на будущее); текущий путь не использует
                break
            task._run()

    # ------------------------------------------------------------------
    # Публичный контракт (совместим с прежним ChainThreadPool)
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        self.is_initialized = True
        return True

    def shutdown(self, wait: bool = True) -> bool:
        """Остановить воркеры пула. ``wait`` — семантическая совместимость с прежним API."""
        self._stop_workers()
        if self._owns_manager:
            self._worker_manager.shutdown()
        self.is_initialized = False
        return True

    @property
    def max_workers(self) -> int:
        return self._max_workers

    @property
    def step_timeout(self) -> float:
        return self._step_timeout

    def submit(self, operation: Any, payload: Any, context: Any) -> _PoolTask:
        """Поставить одну операцию в очередь пула, вернуть handle."""
        task = _PoolTask(operation, payload, context)
        self._in_queue.put(task)
        return task

    def submit_bundle(
        self,
        steps: list[Any],  # list[RunnableStep]
        frame: Any,  # np.ndarray (или иной payload с .copy())
        context: Any,  # ChainContext
    ) -> list[_PoolTask]:
        """Отправить шаги бандла на параллельное исполнение.

        Каждый шаг получает ``frame.copy()`` для thread-safety (как раньше).
        """
        return [self.submit(step.operation, frame.copy(), context) for step in steps]

    def collect_results(
        self,
        handles: list[_PoolTask],
        steps: list[Any],  # list[RunnableStep]
        timeout: float | None = None,
    ) -> list[tuple[Any, Any]]:
        """Дождаться результатов всех задач с общим бюджетом timeout.

        Зависшие задачи (не успевшие в бюджет) → ``TimeoutError`` в результате
        (worst-case queue latency покрывается ``step_timeout``).
        """
        actual_timeout = timeout if timeout is not None else self._step_timeout
        deadline = time.monotonic() + actual_timeout

        results: list[tuple[Any, Any]] = []
        for handle, step in zip(handles, steps):
            remaining = max(0.0, deadline - time.monotonic())
            try:
                results.append((step, handle.result(timeout=remaining)))
            except TimeoutError:
                self._log_warning(
                    f"Операция '{step.node.operation_ref}' (node={step.node.node_id})"
                    f" превысила timeout {actual_timeout}s"
                )
                results.append(
                    (
                        step,
                        TimeoutError(f"Timeout {actual_timeout}s для {step.node.operation_ref}"),
                    )
                )
            except Exception as exc:  # noqa: BLE001 — исключение операции отдаём как результат
                results.append((step, exc))

        return results

    def resize(self, max_workers: int) -> None:
        """Пересоздать пул с новым размером (stop N старых + create N новых).

        worker_module не даёт hot-resize «изменить max_workers без пересоздания
        потоков» — приемлемая деградация, resize не hot-path.
        """
        with self._lock:
            self._stop_workers()
            self._max_workers = max(1, max_workers)
            self._start_workers()


__all__ = ["WorkerPoolExecutor"]
