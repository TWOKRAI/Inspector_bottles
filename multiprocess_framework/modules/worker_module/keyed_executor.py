# -*- coding: utf-8 -*-
"""
KeyedExecutor — исполнитель с порядком по ключу (Task 1.9a, ADR-WRK-005 в DECISIONS.md модуля).

Stability: lite. Клиенты знают только протокол ``OrderedExecutor`` (``worker_module.interfaces``).

Public API:
    - KeyedExecutor — реализация ``OrderedExecutor`` + ``Stoppable`` (submit / request_stop / join_until / shutdown)
    - SYSTEM_STOPPING, EXECUTOR_BUSY — коды отказа в поле ``error`` ответа

Purpose (что делает):
    - операции с пересекающимися ключами исполняются строго в порядке подачи;
    - с непересекающимися — параллельно (до ``max_workers`` одновременно);
    - ``key=None`` — «все ключи»: ждёт всех ранее поданных и задерживает всех поданных позже;
    - ``serial=True`` — один рабочий, все операции в порядке подачи;
    - ``submit`` никогда не блокирует: на потолке ``max_pending`` — отказ ``executor_busy``;
    - ``reply`` каждой операции зовётся ровно один раз.

Устройство (D2 брифа T1.9a) — обобщение ``_run_when_child_ready`` (ADR-PMM-024):
    одна общая очередь ``pending`` в порядке подачи + счётчик ``running`` исполняемых ключей +
    флаг ``running_all`` (исполняется операция ``None``). Запись исполнима, если её ключ не
    пересекается с ``running``, нет ``running_all`` и ключ не пересекается с ключами всех более
    ранних записей ``pending``. Рабочий под ``Condition`` берёт первую исполнимую запись —
    дедлока нет (рабочий не ждёт конкретную операцию), голодания нет (запись ждёт только более ранние).

Потоки — только через ``WorkerManager`` (SYSTEM-воркеры ``keyed-<name>-<i>``, создаются один раз
в конструкторе, ``pause_all`` и GUI worker CRUD их не трогают).

Лок исполнителя никогда не держится поверх ``action``, ``reply`` и ``should_reject``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter, deque
from collections.abc import Callable
from typing import Any

from ..logger_module import get_std_logger
from .core.thread_config import ThreadConfig
from .types import ExecutionMode, WorkerType

__all__ = ["KeyedExecutor", "SYSTEM_STOPPING", "EXECUTOR_BUSY"]

#: Отказ «исполнитель закрыт / потребитель снимает очередь» (новый dict на каждый ответ).
SYSTEM_STOPPING = "system_stopping"
#: Отказ «очередь на потолке max_pending».
EXECUTOR_BUSY = "executor_busy"

# Состояния записи очереди: переход QUEUED→TAKEN или QUEUED→REJECTED — только под локом.
_QUEUED = 0
_TAKEN = 1
_REJECTED = 2

# Маркер «текущий поток не исполняет операцию этого исполнителя» (thread-local).
_NO_OP = object()

# Период пробуждения рабочего: проверка stop_event от WorkerManager.
_WAIT_S = 0.1


def _refusal(error: str) -> dict[str, Any]:
    return {"success": False, "error": error}


def _label(action: Callable[[], Any]) -> str:
    """Имя операции для логов (``__name__`` замыкания или тип вызываемого)."""
    return getattr(action, "__name__", None) or type(action).__name__


class _Op:
    """Запись очереди. Поля меняются только под локом исполнителя (кроме неизменных)."""

    __slots__ = ("action", "key", "reply", "state", "label")

    def __init__(self, action: Callable[[], Any], key: frozenset[str] | None, reply: Callable[[Any], None]) -> None:
        self.action = action
        self.key = key
        self.reply = reply
        self.state = _QUEUED
        self.label = _label(action)


class KeyedExecutor:
    """Исполнитель с порядком по ключу; реализует ``OrderedExecutor`` и ``Stoppable``.

    Args:
        name: имя исполнителя (имена воркеров ``keyed-<name>-<i>``, имя логгера).
        worker_manager: ``WorkerManager`` процесса — обязателен, потоки только через него.
        max_pending: потолок ЖДУЩИХ операций (исполняемые не считаются); на потолке — ``executor_busy``.
        serial: ``True`` — один рабочий, все операции в порядке подачи (``max_workers`` игнорируется).
        max_workers: число постоянных рабочих при ``serial=False``.
        should_reject: ``() -> bool``; ``True`` — новые ``submit`` и вся очередь получают
            ``system_stopping``. Без защёлки, вне лока; исключение в нём считается ``True``.
        log: логгер; ``None`` → ``multiprocess_framework.worker_module.keyed_executor.<name>``.

    Raises:
        ValueError: ``max_pending``/``max_workers`` < 1 или имя воркера занято в ``worker_manager``.

    После конструктора исполнитель готов (рабочие запущены), отдельного ``start()`` нет.
    """

    def __init__(
        self,
        name: str,
        *,
        worker_manager: Any,
        max_pending: int = 64,
        serial: bool = False,
        max_workers: int = 4,
        should_reject: Callable[[], bool] | None = None,
        log: logging.Logger | None = None,
    ) -> None:
        if worker_manager is None:
            raise ValueError("KeyedExecutor: worker_manager обязателен (потоки только через WorkerManager)")
        if max_pending < 1:
            raise ValueError(f"KeyedExecutor '{name}': max_pending должен быть >= 1, получено {max_pending}")
        workers = 1 if serial else max_workers
        if workers < 1:
            raise ValueError(f"KeyedExecutor '{name}': max_workers должен быть >= 1, получено {max_workers}")

        self.name = name
        self._max_pending = max_pending
        self._serial = serial
        self._should_reject = should_reject
        # Через logger_module (страж test_std_logger_guard): при поднятом LoggerManager — его каналы,
        # без него — stdlib-логгер с точным именем ниже (его ловит caplog).
        self._log = log or get_std_logger(
            "worker", fallback_name=f"multiprocess_framework.worker_module.keyed_executor.{name}"
        )

        self._cond = threading.Condition(threading.Lock())
        self._pending: deque[_Op] = deque()
        self._running: Counter[str] = Counter()
        self._running_all = False
        self._active: list[_Op] = []  # исполняемые сейчас (рабочими и на месте), для join_until и serial
        self._closed = False
        self._busy_warned = False  # один WARNING executor_busy на эпизод (до опустевшей очереди)
        self._live_workers = workers
        self._local = threading.local()

        target = self._worker_loop
        for i in range(workers):
            worker_name = f"keyed-{name}-{i}"
            config = ThreadConfig(
                worker_type=WorkerType.SYSTEM,
                restart_on_failure=False,
                execution_mode=ExecutionMode.LOOP,
            )
            if not worker_manager.create_worker(worker_name, target, config, auto_start=True):
                # Уже запущенные рабочие этого исполнителя гасим; несозданные не ждём.
                with self._cond:
                    self._live_workers -= workers - i
                self.request_stop()
                raise ValueError(
                    f"KeyedExecutor '{name}': воркер '{worker_name}' не создан (имя занято в WorkerManager)"
                )

    # ------------------------------------------------------------------
    # OrderedExecutor
    # ------------------------------------------------------------------

    def submit(
        self,
        action: Callable[[], Any],
        key: frozenset[str] | None,
        reply: Callable[[Any], None],
        *,
        inline_if_idle: bool = False,
    ) -> bool:
        """Подать операцию.

        Pre: исполнитель не закрыт и ``should_reject()`` не ``True``; иначе ``reply(system_stopping)``
            сразу на вызывающем потоке, возврат ``False``.
        Post: ``reply`` зовётся ровно один раз — результат ``action``; исключение ``action`` →
            ``{"success": False, "error": "<тип>: <текст>"}``; отказ → ``system_stopping`` / ``executor_busy``.
            Исключение внутри ``reply`` — ``log.error``, исполнитель живёт.

        Returns:
            ``True`` — поставлено в очередь; ``False`` — ``reply`` уже вызван на вызывающем потоке
            (исполнено на месте или отказ). Никогда не блокирует.

        Повторный вход (вызов из ``action`` этого исполнителя): ключ ⊆ ключа текущей операции
        (при ``serial=True`` — любой) → исполнение на месте как часть родителя; иначе обычная постановка.
        ``action`` не вправе ждать ``reply`` вложенной операции.
        """
        if key is not None:
            key = frozenset(key)

        if self._reject_requested():
            self._deliver(reply, _refusal(SYSTEM_STOPPING), _label(action))
            return False

        parent = getattr(self._local, "op_key", _NO_OP)
        if parent is not _NO_OP and (self._serial or parent is None or (key is not None and key <= parent)):
            # Вложенная операция — часть родителя: его ключи уже заняты, очередь не трогаем.
            with self._cond:
                closed = self._closed
            if closed:
                self._deliver(reply, _refusal(SYSTEM_STOPPING), _label(action))
            else:
                self._execute(action, key, reply, _label(action))
            return False

        op = _Op(action, key, reply)
        refusal: str | None = None
        warn_busy = False
        with self._cond:
            if self._closed:
                refusal = SYSTEM_STOPPING
            elif inline_if_idle and self._idle_for_locked(key):
                # Решение «свободен → на месте» и захват ключа — под одним локом.
                op.state = _TAKEN
                self._mark_running_locked(op)
            elif len(self._pending) >= self._max_pending:
                refusal = EXECUTOR_BUSY
                warn_busy = not self._busy_warned
                self._busy_warned = True
            else:
                self._pending.append(op)
                self._cond.notify_all()
                return True

        if refusal is not None:
            if warn_busy:
                self._log.warning(
                    "KeyedExecutor '%s': очередь на потолке max_pending=%d — отказ executor_busy (операция '%s'); "
                    "следующий WARNING — после опустевшей очереди",
                    self.name,
                    self._max_pending,
                    op.label,
                )
            self._deliver(reply, _refusal(refusal), op.label)
            return False

        # inline_if_idle: ключ захвачен, исполняем на вызывающем потоке.
        try:
            self._execute(action, key, reply, op.label)
        finally:
            with self._cond:
                self._unmark_running_locked(op)
                self._cond.notify_all()
        return False

    # ------------------------------------------------------------------
    # Stoppable
    # ------------------------------------------------------------------

    def request_stop(self) -> None:
        """Фаза 1: закрыть приём и снять очередь (каждой снятой — ``system_stopping``). Идемпотентен, не блокирует."""
        with self._cond:
            self._closed = True
            dropped = self._drain_locked()
            self._cond.notify_all()
        self._reject_all(dropped)

    def join_until(self, deadline: float) -> bool:
        """Фаза 2: ждать текущие операции и выход рабочих до ``deadline`` (``time.monotonic()``).

        ``True`` — всё завершилось; иначе ``False`` + WARNING с именами незавершённых операций.
        Без предшествующего ``request_stop`` рабочие не выходят — вернётся ``False`` к сроку.
        """
        with self._cond:
            while self._live_workers > 0 or self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._cond.wait(min(remaining, _WAIT_S))
            else:
                return True
            stuck = [op.label for op in self._active]
            live = self._live_workers
        self._log.warning(
            "KeyedExecutor '%s': не остановлен к сроку — исполняются %s, живых рабочих %d",
            self.name,
            stuck or "нет операций",
            live,
        )
        return False

    def shutdown(self, deadline: float) -> bool:
        """``request_stop(); return join_until(deadline)``."""
        self.request_stop()
        return self.join_until(deadline)

    # ------------------------------------------------------------------
    # Рабочий
    # ------------------------------------------------------------------

    def _worker_loop(self, stop_event: threading.Event, pause_event: threading.Event) -> None:
        """Цель воркера ``WorkerManager``: брать исполнимые записи до закрытия.

        ``pause_event`` не используется: SYSTEM-воркер, ``pause_all`` его не ставит на паузу.
        Взведённый ``stop_event`` (``stop_all_workers``) → ``request_stop()`` всего исполнителя:
        очередь получает ``system_stopping``, а не остаётся без ответа.
        """
        try:
            while True:
                with self._cond:
                    if not (self._closed or stop_event.is_set() or self._has_runnable_locked()):
                        self._cond.wait(_WAIT_S)
                    if self._closed:
                        return
                    stopping = stop_event.is_set()
                    has_pending = bool(self._pending)
                    runnable = self._has_runnable_locked()
                if stopping:
                    self.request_stop()
                    return
                if not has_pending:
                    continue

                # should_reject — вне лока, на каждом пробуждении при непустой очереди (раз в _WAIT_S,
                # даже если ничего не исполнимо: ждущие за занятым ключом снимаются, не дожидаясь его).
                # Ревью р.1 п.2.
                if self._reject_requested():
                    with self._cond:
                        dropped = self._drain_locked()
                    self._reject_all(dropped)
                    continue
                if not runnable:
                    continue

                with self._cond:
                    op = self._take_runnable_locked()
                if op is None:
                    continue  # запись взял другой рабочий
                try:
                    self._execute(op.action, op.key, op.reply, op.label)
                finally:
                    with self._cond:
                        self._unmark_running_locked(op)
                        self._cond.notify_all()
        except Exception:  # noqa: BLE001 — рабочий не должен падать молча
            self._log.error("KeyedExecutor '%s': рабочий упал", self.name, exc_info=True)
        finally:
            with self._cond:
                abnormal = not self._closed
            if abnormal:
                # Рабочий ушёл не по закрытию (исключение, в том числе BaseException из action):
                # закрыть исполнитель, иначе очередь осталась бы без ответа и без рабочего.
                # До снятия счётчика живых: join_until == True гарантирует, что исполнитель закрыт.
                self._log.error("KeyedExecutor '%s': рабочий вышел не по закрытию — исполнитель закрыт", self.name)
                self.request_stop()
            with self._cond:
                self._live_workers -= 1
                self._cond.notify_all()

    # ------------------------------------------------------------------
    # Исполнение и ответ (вне лока)
    # ------------------------------------------------------------------

    def _execute(
        self,
        action: Callable[[], Any],
        key: frozenset[str] | None,
        reply: Callable[[Any], None],
        label: str,
    ) -> None:
        """Исполнить ``action`` и ровно раз позвать ``reply``. Ключ на время ``action`` — в thread-local
        (правило повторного входа); сохранение/восстановление — на случай вложенности."""
        saved = getattr(self._local, "op_key", _NO_OP)
        self._local.op_key = key
        try:
            result = action()
        except Exception as exc:  # noqa: BLE001 — исключение операции превращается в отказ
            self._log.error("KeyedExecutor '%s': операция '%s' упала: %s", self.name, label, exc, exc_info=True)
            result = _refusal(f"{type(exc).__name__}: {exc}")
        except BaseException as exc:
            # SystemExit / KeyboardInterrupt / GeneratorExit: ответ всё равно ровно один,
            # затем исключение идёт дальше (рабочий выходит, исполнитель закрывается —
            # см. finally в _worker_loop). Ревью р.1 п.1.
            self._local.op_key = saved
            self._log.error("KeyedExecutor '%s': операция '%s' прервана %s", self.name, label, type(exc).__name__)
            self._deliver(reply, _refusal(f"{type(exc).__name__}: {exc}"), label)
            raise
        finally:
            self._local.op_key = saved
        self._deliver(reply, result, label)

    def _deliver(self, reply: Callable[[Any], None], payload: Any, label: str) -> None:
        try:
            reply(payload)
        except Exception:  # noqa: BLE001 — исключение в reply не валит рабочего/вызывающего
            self._log.error(
                "KeyedExecutor '%s': reply операции '%s' бросил исключение", self.name, label, exc_info=True
            )

    def _reject_all(self, ops: list[_Op]) -> None:
        for op in ops:
            self._deliver(op.reply, _refusal(SYSTEM_STOPPING), op.label)

    def _reject_requested(self) -> bool:
        """``should_reject()`` вне лока; исключение в нём → ``log.error`` и ``True``."""
        if self._should_reject is None:
            return False
        try:
            return bool(self._should_reject())
        except Exception:  # noqa: BLE001
            self._log.error(
                "KeyedExecutor '%s': should_reject бросил исключение — считаю True", self.name, exc_info=True
            )
            return True

    # ------------------------------------------------------------------
    # Состояние (только под self._cond)
    # ------------------------------------------------------------------

    def _drain_locked(self) -> list[_Op]:
        dropped = list(self._pending)
        self._pending.clear()
        for op in dropped:
            op.state = _REJECTED
        self._busy_warned = False
        return dropped

    def _mark_running_locked(self, op: _Op) -> None:
        self._active.append(op)
        if op.key is None:
            self._running_all = True
        else:
            self._running.update(op.key)

    def _unmark_running_locked(self, op: _Op) -> None:
        self._active.remove(op)
        if op.key is None:
            self._running_all = False
        else:
            self._running.subtract(op.key)
            for k in op.key:
                if self._running[k] <= 0:
                    del self._running[k]

    def _key_busy_locked(self, key: frozenset[str]) -> bool:
        return self._running_all or any(k in self._running for k in key)

    def _idle_for_locked(self, key: frozenset[str] | None) -> bool:
        """Ключ не пересекается ни с исполняемыми, ни с ждущими (serial: ничего не исполняется и не ждёт)."""
        if self._serial or key is None:
            return not self._active and not self._pending
        if self._key_busy_locked(key):
            return False
        for op in self._pending:
            if op.key is None or not op.key.isdisjoint(key):
                return False
        return True

    def _runnable_index_locked(self) -> int:
        """Индекс первой исполнимой записи ``pending`` или -1."""
        if not self._pending:
            return -1
        if self._serial:
            return 0 if not self._active else -1
        if self._running_all:
            return -1
        seen: set[str] = set()
        for idx, op in enumerate(self._pending):
            if op.key is None:
                # None исполнима, только когда ничего не исполняется и впереди никого нет;
                # дальше накопленное множество = «всё» — просмотр окончен.
                return idx if idx == 0 and not self._active else -1
            if not self._key_busy_locked(op.key) and seen.isdisjoint(op.key):
                return idx
            seen.update(op.key)
        return -1

    def _has_runnable_locked(self) -> bool:
        return self._runnable_index_locked() >= 0

    def _take_runnable_locked(self) -> _Op | None:
        idx = self._runnable_index_locked()
        if idx < 0:
            return None
        op = self._pending[idx]
        del self._pending[idx]
        op.state = _TAKEN
        self._mark_running_locked(op)
        if not self._pending:
            self._busy_warned = False  # эпизод executor_busy окончен
        return op
