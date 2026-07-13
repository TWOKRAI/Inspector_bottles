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

Стоп-механика — сентинелы: воркеры блокируются в ``get()`` (без poll — нет
idle-пробуждений), останов кладёт по одному ``None``-сентинелу на воркер. Это даёт
честный дренаж очереди при ``shutdown(wait=True)`` (сентинелы ложатся ПОСЛЕ хвоста
задач) и гарантию, что зомби после join-таймаута доисполнит текущую задачу, возьмёт
сентинел и умрёт, а не будет жить вечно на общей очереди. ``stop_event``
WorkerManager остаётся backstop'ом (снимает зомби на верхе цикла), сентинел его
дополняет, не заменяет.

Почему обёртка, а НЕ расширение ``IWorkerManager`` под submit/Future: единственный
потребитель submit/collect-паттерна — chain-пул. Расширять публичный контракт
worker_module (LOOP-воркеры почти в каждом процессе) ради узкого кейса — риск для
стабильного API. Обёртка использует ТОЛЬКО существующий публичный контракт
(``create_worker``/``remove_worker``/``shutdown``). ``remove_worker`` добавлен в
``IWorkerManager`` как выравнивание интерфейса под уже существующий публичный метод
WorkerManager (не новая возможность) — см. ADR-CHN-009 M3.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from typing import Any

from ...base_manager import BaseManager, ObservableMixin
from ...worker_module import ExecutionMode, IWorkerManager, ThreadConfig, WorkerManager

# Сентинел остановки воркера: воркер, забравший ``None``, выходит из цикла.
_STOP_SENTINEL = None


class _PoolTimeout(Exception):
    """Внутренний маркер: ``_PoolTask.result`` не дождался за отведённый timeout.

    Отдельный от встроенного ``TimeoutError`` класс, чтобы ``collect_results`` не
    маскировал бизнес-``TimeoutError`` шага под «превысила timeout пула» (M2).
    """


class _PoolTask:
    """Задача пула: операция + payload + Event для блокирующего ожидания.

    Аналог ``concurrent.futures.Future`` в объёме, нужном chain-пулу: одна
    операция, один результат/исключение, ``result(timeout)`` для ожидания.
    Event-based (как ``PendingTask`` в WorkerPoolDispatcher) — без зависимости
    от ``concurrent.futures``.
    """

    __slots__ = ("_operation", "_payload", "_context", "_event", "_value", "_exc", "_cancelled")

    def __init__(self, operation: Any, payload: Any, context: Any) -> None:
        self._operation = operation
        self._payload = payload
        self._context = context
        self._event = threading.Event()
        self._value: Any = None
        self._exc: BaseException | None = None
        self._cancelled = False

    def _run(self) -> None:
        """Исполнить операцию (вызывается воркером пула). Исключение — в слот.

        Отменённая (истёкшая по timeout / сброшенная при shutdown) задача — no-op:
        иначе её side-state (напр. ``last_detections`` на shared-объекте) загрязнил
        бы следующий бандл кросс-кадровой контаминацией (H1).

        ``BaseException`` ловится наравне с ``Exception`` (паритет с прежним пулом):
        иначе исключение убило бы LOOP-воркер навсегда, а ``result()`` вернул бы
        ``None`` как «успех» (H2).
        """
        if self._cancelled:
            return
        try:
            self._value = self._operation.execute(self._payload, self._context)
        except BaseException as exc:  # noqa: BLE001 — политика ошибок решается вызывающим
            self._exc = exc
        finally:
            self._event.set()

    def cancel(self) -> None:
        """Пометить отменённой: ещё не начатая задача не исполнится (H1)."""
        self._cancelled = True

    def result(self, timeout: float | None = None) -> Any:
        """Дождаться результата. ``_PoolTimeout`` при истечении, иначе значение/исключение."""
        if not self._event.wait(timeout):
            raise _PoolTimeout(f"Task did not complete within {timeout}s")
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
        worker_manager: IWorkerManager | None = None,
        manager_name: str = "WorkerPoolExecutor",
    ) -> None:
        BaseManager.__init__(self, manager_name=manager_name)
        ObservableMixin.__init__(self, managers={"logger": logger})

        self._max_workers = max(1, max_workers)
        self._step_timeout = step_timeout
        self._lock = threading.Lock()
        self._in_queue: queue.Queue[_PoolTask | None] = queue.Queue()
        self._shutdown = False

        # Уникальный префикс имён воркеров на ЭКЗЕМПЛЯР: несколько пулов на общем
        # (инжектированном) WorkerManager не должны коллизировать по ``chain_pool_i``
        # и сносить чужих воркеров при shutdown (H3).
        self._name_prefix = f"{manager_name}_{uuid.uuid4().hex[:8]}"

        self._owns_manager = worker_manager is None
        self._worker_manager: IWorkerManager = worker_manager or WorkerManager(manager_name=f"{manager_name}Workers")
        self._worker_manager.initialize()

        self._worker_names: list[str] = []
        self._start_workers()

    # ------------------------------------------------------------------
    # Жизненный цикл воркеров пула
    # ------------------------------------------------------------------

    def _start_workers(self) -> None:
        """Создать и запустить ``self._max_workers`` персистентных LOOP-воркеров.

        Результат ``create_worker`` проверяется: False → RuntimeError (иначе тихий
        пустой пул при вере в N воркеров — H3).
        """
        config = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        for i in range(self._max_workers):
            name = f"{self._name_prefix}_pool_{i}"
            ok = self._worker_manager.create_worker(name, self._pool_loop, config, auto_start=True)
            if not ok:
                raise RuntimeError(
                    f"WorkerPoolExecutor: не удалось создать воркер '{name}' (WorkerManager.create_worker вернул False)"
                )
            self._worker_names.append(name)

    def _stop_workers(self) -> None:
        """Остановить и снять с учёта все воркеры пула. Вызывается под ``self._lock``.

        По одному сентинелу на воркер (будит блокирующий ``get()`` → выход из
        цикла), затем ``remove_worker`` (stop_event backstop + join + снятие с
        учёта в реестре — иначе имя осталось бы занятым STOPPED-воркером).
        """
        for _ in self._worker_names:
            self._in_queue.put(_STOP_SENTINEL)
        for name in self._worker_names:
            self._worker_manager.remove_worker(name)
        self._worker_names.clear()

    def _drain_and_cancel(self) -> None:
        """Отменить все задачи в очереди (shutdown(wait=False)). Под ``self._lock``."""
        while True:
            try:
                task = self._in_queue.get_nowait()
            except queue.Empty:
                break
            if task is not None:
                task.cancel()

    def _pool_loop(self, stop_event: threading.Event, pause_event: threading.Event) -> None:
        """Тело LOOP-воркера: блокирующий разбор очереди до сентинела/stop_event.

        Блокирующий ``get()`` — без poll (нет N×idle-пробуждений). Сентинел
        (``None``) → выход. ``stop_event`` на верхе цикла — backstop: зомби,
        доисполнивший зависшую задачу после join-таймаута, увидит его и выйдет,
        не потребляя чужой сентинел.
        """
        while not stop_event.is_set():
            task = self._in_queue.get()  # блокирующий
            if task is _STOP_SENTINEL:
                break
            task._run()

    # ------------------------------------------------------------------
    # Публичный контракт (совместим с прежним ChainThreadPool)
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        self.is_initialized = True
        return True

    def shutdown(self, wait: bool = True) -> bool:
        """Остановить воркеры пула.

        ``wait=True`` — честный дренаж: сентинелы ложатся ПОСЛЕ хвоста задач,
        воркеры доисполняют очередь. ``wait=False`` — отменить оставшиеся задачи
        (истёкшие/невостребованные) до постановки сентинелов.
        """
        with self._lock:
            if self._shutdown:
                return True
            self._shutdown = True
            if not wait:
                self._drain_and_cancel()
            self._stop_workers()
            owns = self._owns_manager
        if owns:
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
        """Поставить одну операцию в очередь пула, вернуть handle.

        После ``shutdown`` → RuntimeError (паритет со старым пулом — не молча
        теряем задачу).
        """
        if self._shutdown:
            raise RuntimeError("WorkerPoolExecutor: submit после shutdown")
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

        Истёкшие по timeout задачи отменяются (``cancel``) — не начатая задача не
        исполнится позже (H1). Бизнес-``TimeoutError`` шага НЕ маскируется под
        timeout пула — ловится только внутренний ``_PoolTimeout`` (M2).
        """
        actual_timeout = timeout if timeout is not None else self._step_timeout
        deadline = time.monotonic() + actual_timeout

        results: list[tuple[Any, Any]] = []
        for handle, step in zip(handles, steps):
            remaining = max(0.0, deadline - time.monotonic())
            try:
                results.append((step, handle.result(timeout=remaining)))
            except _PoolTimeout:
                handle.cancel()  # ещё не начатая задача не исполнится позже (H1)
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
            except BaseException as exc:  # noqa: BLE001 — исключение операции отдаём как результат
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
