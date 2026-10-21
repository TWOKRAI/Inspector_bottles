# -*- coding: utf-8 -*-
"""
ExecutorManager — именованные исполнители процесса (Task 1.9m, ADR-WRK-006).

Сотрудник процесса фреймворка: создаёт ``KeyedExecutor`` из конфига процесса или по вызову кода,
принимает готовые объекты протокола ``OrderedExecutor`` по имени, отдаёт их ``CommandManager``
по имени (``register_command(executor="io")``), владеет созданными исполнителями и показывает их
через ``describe()``.

Владение:
    * созданный исполнитель отдаётся области менеджера (``scope.own``) — закрывается её общим сроком;
      без области — лежит в ``_unowned`` и закрывается в ``_on_shutdown`` (одно место закрытия);
    * зарегистрированный объект менеджер только маршрутизирует по имени — ``request_stop`` /
      ``join_until`` у него не зовёт (владелец остаётся у регистрирующего).

Процесс без исполнителей платит ноль: ни потока, ни строки лога.

Stability: lite (``new-lite``, один файл рядом с ядром ``keyed_executor.py``).
Контракт — ``worker_module/interfaces.py`` (``IExecutorRegistry``, ``IExecutorManager``).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ConfigDict, Field, ValidationError

from ..base_manager import BaseManager, ObservableMixin, check_scope_name
from ..base_manager.interfaces import ScopeClosedError
from ..data_schema_module import SchemaBase
from .interfaces import OrderedExecutor
from .keyed_executor import KeyedExecutor

__all__ = ["ExecutorManager", "ExecutorSpec"]

# Общий срок закрытия исполнителей, не попавших в область (менеджер вне ``ProcessModule``), секунд.
_UNOWNED_JOIN_S = 2.0

# Не опубликованная в API величина: ``describe()`` честно называет то, чего у ядра нет.
_UNAVAILABLE = ["pending_depth", "running_keys"]


class ExecutorSpec(SchemaBase):
    """Схема записи ``executors`` конфига процесса: умолчания ``KeyedExecutor`` (``keyed_executor.py``).

    ``extra="forbid"``: опечатка в ключе — громкий отказ записи, а не тихий исполнитель с умолчаниями.
    ``should_reject`` и ``log`` в схеме нет — это код, не данные.
    """

    model_config = ConfigDict(**SchemaBase.model_config, extra="forbid")

    kind: Literal["keyed"] = "keyed"
    serial: bool = False
    max_workers: int = Field(default=4, ge=1)
    max_pending: int = Field(default=64, ge=1)


class _OwnedExecutor:
    """Приватная обёртка ``Stoppable`` над созданным исполнителем (D5).

    ``join_until`` со своего рабочего не ждёт (рабочий считал бы сам себя живым до срока).
    Признак «свой рабочий» — точное имя потока из ``thread_names``.
    """

    def __init__(
        self,
        executor: OrderedExecutor,
        name: str,
        thread_names: frozenset[str],
        warn: Callable[[str], Any],
    ) -> None:
        self._executor = executor
        self._name = name
        self._thread_names = thread_names
        self._warn = warn

    def request_stop(self) -> None:
        self._executor.request_stop()

    def join_until(self, deadline: float) -> bool:
        if threading.current_thread().name in self._thread_names:
            self._warn(f"Executor '{self._name}' закрывается со своего рабочего — без ожидания")
            return False
        return self._executor.join_until(deadline)

    def __repr__(self) -> str:
        return f"<executor '{self._name}'>"


@dataclass(frozen=True)
class _Entry:
    """Запись реестра менеджера; заменяется целиком под локом, поэтому снимок читается без гонки."""

    kind: Literal["reserved", "keyed", "registered"]
    executor: Any = None
    source: Literal["config", "code"] = "code"
    spec: ExecutorSpec | None = None
    thread_names: frozenset[str] = frozenset()
    worker_names: tuple[str, ...] = ()
    owned: bool = False


_RESERVED = "reserved"


def _spec_error_text(exc: ValidationError) -> str:
    """Строки ``<loc>: <msg>`` через ``; `` — без входных значений."""
    parts = []
    for err in exc.errors(include_input=False, include_url=False):
        loc = ".".join(str(item) for item in err["loc"])
        parts.append(f"{loc}: {err['msg']}" if loc else str(err["msg"]))
    return "; ".join(parts)


class ExecutorManager(BaseManager, ObservableMixin):
    """Именованные исполнители процесса. Контракт — ``IExecutorManager`` (``worker_module/interfaces.py``).

    Состояние — ``dict[имя, _Entry]`` под ``threading.Lock``. Лок не держится поверх конструктора
    ``KeyedExecutor``, ``scope.own``, ``get_worker_status`` и логов: имя резервируется под локом,
    исполнитель создаётся вне лока, запись фиксируется под локом.
    """

    def __init__(
        self,
        manager_name: str,
        *,
        worker_manager: Any,
        process: Any = None,
        managers: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        BaseManager.__init__(self, manager_name=manager_name, process=process)
        ObservableMixin.__init__(self, managers=managers or {}, config=config or {})
        self._worker_manager = worker_manager
        self._lock = threading.Lock()
        self._entries: dict[str, _Entry] = {}
        self._unowned: list[_OwnedExecutor] = []
        self._closed = False

    # ------------------------------------------------------------------
    # BaseManager
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """Без потоков и без строки лога."""
        self.is_initialized = True
        return True

    def _on_shutdown(self) -> bool:
        """Закрыть исполнители вне области (всегда: область могла быть привязана позже создания).

        Исполнители области уже закрыты ``shutdown()`` шаблоном (``scope.close()`` идёт первым).
        """
        with self._lock:
            self._closed = True
            unowned = list(self._unowned)
            self._unowned.clear()
        ok = True
        for owned in unowned:
            try:
                owned.request_stop()
            except Exception as exc:  # один сбой не роняет соседей
                self._log_error(f"Executor {owned!r}: request_stop упал: {type(exc).__name__}: {exc}")
                ok = False
        deadline = time.monotonic() + _UNOWNED_JOIN_S
        for owned in unowned:
            try:
                ok = owned.join_until(deadline) and ok
            except Exception as exc:
                self._log_error(f"Executor {owned!r}: join_until упал: {type(exc).__name__}: {exc}")
                ok = False
        self.is_initialized = False
        return ok

    # ------------------------------------------------------------------
    # IExecutorRegistry / IExecutorManager
    # ------------------------------------------------------------------

    def get(self, name: str) -> OrderedExecutor | None:
        """Исполнитель по имени или ``None``; не бросает."""
        with self._lock:
            entry = self._entries.get(name)
        return None if entry is None else entry.executor

    def names(self) -> list[str]:
        """Все имена (созданные и зарегистрированные) в порядке появления; резервы не считаются."""
        with self._lock:
            return [name for name, entry in self._entries.items() if entry.kind != _RESERVED]

    def create(
        self,
        name: str,
        spec: Mapping[str, Any] | None = None,
        *,
        should_reject: Callable[[], bool] | None = None,
    ) -> OrderedExecutor:
        return self._create(name, spec, should_reject, source="code")

    def register(self, name: str, executor: OrderedExecutor) -> None:
        check_scope_name(name)
        if not callable(getattr(executor, "submit", None)):
            raise TypeError(f"register '{name}': у executor нет вызываемого submit ({type(executor).__name__})")
        with self._lock:
            if name in self._entries:
                raise ValueError(f"register '{name}': имя уже занято")
            self._entries[name] = _Entry(kind="registered", executor=executor, source="code")

    def load_config(self, section: Mapping[str, Mapping[str, Any]] | None) -> list[str]:
        if section is None:
            return []
        if not isinstance(section, Mapping):
            self._log_error(f"executors: секция конфига должна быть словарём, получено {type(section).__name__}")
            return []
        created: list[str] = []
        for name, spec in section.items():
            try:
                self._create(name, spec, None, source="config")
            except Exception as exc:  # своя попытка на запись: сосед не страдает (принцип 5)
                reason = str(exc) if isinstance(exc, (ValueError, TypeError)) else f"{type(exc).__name__}: {exc}"
                self._log_error(f"executors: запись '{name}' пропущена: {reason}")
                continue
            created.append(name)
        return created

    def is_executor_thread(self, name: str) -> bool:
        """Текущий поток — рабочий СОЗДАННОГО исполнителя ``name`` (точное имя потока)."""
        with self._lock:
            entry = self._entries.get(name)
        return entry is not None and threading.current_thread().name in entry.thread_names

    def describe(self) -> dict[str, Any]:
        """Снимок под локом; статусы воркеров — вне лока (публичный ``get_worker_status``)."""
        with self._lock:
            snapshot = [(name, entry) for name, entry in self._entries.items() if entry.kind != _RESERVED]
        executors: dict[str, Any] = {}
        for name, entry in snapshot:
            if entry.kind == "registered":
                executors[name] = {
                    "kind": "registered",
                    "source": "code",
                    "type": type(entry.executor).__name__,
                }
                continue
            spec = entry.spec
            assert spec is not None
            workers: dict[str, Any] = {}
            for worker_name in entry.worker_names:
                status = self._worker_manager.get_worker_status(worker_name)
                if status is None:
                    workers[worker_name] = {"is_alive": False, "status": "absent"}
                else:
                    workers[worker_name] = {"is_alive": bool(status["is_alive"]), "status": str(status["status"])}
            executors[name] = {
                "kind": entry.kind,
                "source": entry.source,
                "serial": spec.serial,
                "max_workers": spec.max_workers,
                "max_pending": spec.max_pending,
                "owned": entry.owned,
                "workers": workers,
            }
        return {"executors": executors, "unavailable": list(_UNAVAILABLE)}

    # ------------------------------------------------------------------
    # Создание
    # ------------------------------------------------------------------

    def _create(
        self,
        name: str,
        spec: Mapping[str, Any] | None,
        should_reject: Callable[[], bool] | None,
        *,
        source: Literal["config", "code"],
    ) -> OrderedExecutor:
        check_scope_name(name)
        parsed = self._parse_spec(spec)
        # Имена рабочих и потоков считаются ДО резерва и конструктора: сбой здесь не оставляет ни резерва,
        # ни исполнителя без владельца.
        workers = 1 if parsed.serial else parsed.max_workers
        worker_names = tuple(f"keyed-{name}-{i}" for i in range(workers))
        prefix = self._worker_manager.manager_name
        thread_names = frozenset(f"{prefix}_{worker_name}" for worker_name in worker_names)

        reserved = _Entry(kind=_RESERVED)
        with self._lock:
            if self._closed:
                raise RuntimeError(f"create '{name}': менеджер {self.manager_name} закрыт")
            if name in self._entries:
                raise ValueError(f"create '{name}': имя уже занято")
            self._entries[name] = reserved

        try:
            executor = KeyedExecutor(
                name,
                worker_manager=self._worker_manager,
                max_pending=parsed.max_pending,
                serial=parsed.serial,
                max_workers=parsed.max_workers,
                should_reject=should_reject,
                log=None,
            )
        except BaseException:
            self._drop_reservation(name, reserved)
            raise

        owned = _OwnedExecutor(executor, name, thread_names, self._log_warning)

        in_scope = False
        scope = self.scope
        if scope is not None:
            try:
                # Закрывающаяся/закрытая область сама освобождает ресурс и бросает ScopeClosedError.
                scope.own(owned, name=name, kind="executor")
            except ScopeClosedError:
                self._drop_reservation(name, reserved)
                raise
            except BaseException:
                self._drop_reservation(name, reserved)
                self._stop_now(owned)
                raise
            in_scope = True

        late = False
        with self._lock:
            if self._closed and not in_scope:
                late = True
                if self._entries.get(name) is reserved:
                    del self._entries[name]
            else:
                self._entries[name] = _Entry(
                    kind="keyed",
                    executor=executor,
                    source=source,
                    spec=parsed,
                    thread_names=thread_names,
                    worker_names=worker_names,
                    owned=in_scope,
                )
                if not in_scope:
                    self._unowned.append(owned)
        if late:
            # Закрытие между резервом и записью: на пути без области остановить самим.
            self._stop_now(owned)
            raise RuntimeError(f"create '{name}': менеджер {self.manager_name} закрыт")

        self._log_info(
            f"Executor '{name}' created: kind={parsed.kind}, serial={parsed.serial}, "
            f"max_workers={parsed.max_workers}, max_pending={parsed.max_pending}"
        )
        return executor

    @staticmethod
    def _parse_spec(spec: Mapping[str, Any] | None) -> ExecutorSpec:
        if spec is None:
            return ExecutorSpec()
        if not isinstance(spec, Mapping):
            raise ValueError(f"spec: ожидается словарь, получено {type(spec).__name__}")
        try:
            return ExecutorSpec.model_validate(dict(spec))
        except ValidationError as exc:
            raise ValueError(_spec_error_text(exc)) from None

    def _drop_reservation(self, name: str, reserved: _Entry) -> None:
        """Снять резерв имени на провале создания."""
        with self._lock:
            if self._entries.get(name) is reserved:
                del self._entries[name]

    @staticmethod
    def _stop_now(owned: _OwnedExecutor) -> None:
        owned.request_stop()
        owned.join_until(time.monotonic() + _UNOWNED_JOIN_S)
