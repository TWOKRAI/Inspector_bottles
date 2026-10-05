"""Подписчики издателя, привязанные к области-владельцу (Task 0.3, EVT-003).

Purpose: список подписчиков издателя, где каждая подписка — запись области
``owner`` (``IScope.own``): закрытие владельца снимает подписку, отклонённые
доставки считаются и уходят владельцу (``IScope.note_emits_after_close``).

Хранилище — ``dict[seq, _Sub]`` под ``threading.RLock``; удаление только
``dict.pop(seq, None)`` — gc-финализатор (``_Release``) может войти в этот же
поток посреди секции под локом, а ``pop`` не теряет параллельную вставку.
Под локом нет чужого кода: ``cb``, ``own``, ``note``, ``logging`` — вне лока.
"""

from __future__ import annotations

import itertools
import logging
import threading
import weakref
from collections.abc import Callable

from multiprocess_framework.modules.base_manager.interfaces import IHandle, IScope

__all__ = ["Subscribers"]

_log = logging.getLogger(__name__)

_ERRORS_CAP = 20

# Один счётчик на процесс: два издателя с одним name не займут одно имя записи.
_seq = itertools.count(1)


class _Sub:
    """Одна подписка. Без ``__eq__``: сравнение — по идентичности."""

    __slots__ = ("seq", "cb", "owner_ref", "active", "path")

    def __init__(self, seq: int, cb: Callable[..., object], owner_ref: weakref.ref, path: str) -> None:
        self.seq = seq
        self.cb = cb
        self.owner_ref = owner_ref
        self.active = True
        self.path = path


class _Release:
    """Вызываемое в записи владельца: снять подписку. Не бросает, повтор — no-op.

    Издатель — по ``weakref``: запись владельца не держит издателя. После вызова
    ``_Sub`` отпускается (подписчик не удерживается записью); ``cb`` не обнуляется —
    его ещё может доставить идущая рассылка, она проверит ``active``.
    """

    __slots__ = ("_pub_ref", "_sub")

    def __init__(self, pub: Subscribers, sub: _Sub) -> None:
        self._pub_ref = weakref.ref(pub)
        self._sub: _Sub | None = sub

    def __call__(self) -> None:
        sub = self._sub
        if sub is None:
            return
        self._sub = None
        sub.active = False
        pub = self._pub_ref()
        if pub is not None:
            with pub._lock:
                pub._store.pop(sub.seq, None)


class Subscribers:
    """Подписчики издателя с владельцем-областью.

    ``add(cb, owner=scope)`` — подписка становится записью ``scope``
    (``kind="subscription"``); закрытие ``scope`` или ручки снимает её.
    ``emit`` доставляет по снимку в порядке ``add``; добавленная в ходе рассылки
    в неё не попадает, снятая — в её остаток не попадает.

    **Окно чужого потока:** после возврата ``close()`` владельца или
    ``h.close()`` подписчик может получить ещё одну рассылку, начатую другим
    потоком раньше. В одном потоке окна нет.

    Счётчики: ``errors`` — первые 20 пар ``(путь, "Тип: текст")``,
    ``error_count`` — все исключения подписчиков, ``emits_after_close`` — все
    отклонённые доставки (владелец закрыт или собран без ``close``).
    """

    def __init__(self, name: str) -> None:
        if not isinstance(name, str):
            raise TypeError(f"Subscribers: name — ожидается str, получено {type(name).__name__}")
        if not name or "/" in name:
            raise ValueError("Subscribers: name — нужна непустая строка без '/'")
        self._name = name
        self._lock = threading.RLock()
        self._store: dict[int, _Sub] = {}
        self._errors: list[tuple[str, str]] = []
        self._error_count = 0
        self._emits_after_close = 0
        self._warned_collected = False

    # ---- счётчики -----------------------------------------------------------

    @property
    def errors(self) -> tuple[tuple[str, str], ...]:
        with self._lock:
            return tuple(self._errors)

    @property
    def error_count(self) -> int:
        with self._lock:
            return self._error_count

    @property
    def emits_after_close(self) -> int:
        with self._lock:
            return self._emits_after_close

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    # ---- подписка -----------------------------------------------------------

    def add(self, cb: Callable[..., object], *, owner: IScope) -> IHandle:
        """Подписать ``cb``; подписка — запись ``owner`` (``ScopeClosedError``, если он закрыт)."""
        if not callable(cb):
            raise TypeError(f"Subscribers '{self._name}': cb — ожидается вызываемое, получено {type(cb).__name__}")
        owner_error = TypeError(
            f"Subscribers '{self._name}': owner — ожидается IScope, получено {type(owner).__name__}"
        )
        if not callable(getattr(owner, "own", None)):
            raise owner_error
        try:
            owner_ref = weakref.ref(owner)  # без колбэка: собранный владелец виден в emit
        except TypeError:
            raise owner_error from None
        seq = next(_seq)
        entry_name = f"{self._name}#{seq}"
        sub = _Sub(seq, cb, owner_ref, f"{owner.path}/{entry_name}")
        handle = owner.own(_Release(self, sub), name=entry_name, kind="subscription")
        with self._lock:
            # Владелец мог закрыться между own и этой секцией: _Release уже снял active.
            if sub.active:
                self._store[seq] = sub
        return handle

    # ---- рассылка -----------------------------------------------------------

    def emit(self, *args: object, **kwargs: object) -> int:
        """Доставить всем активным подпискам; вернуть число доставок без исключения."""
        with self._lock:
            snapshot = tuple(self._store.copy().values())
        delivered = 0
        rejected: dict[int, list] = {}  # id(владельца) -> [владелец, n]
        for sub in snapshot:
            if not sub.active:
                owner = sub.owner_ref()
                counted = owner is None or owner.closed
                with self._lock:
                    self._store.pop(sub.seq, None)
                    if counted:
                        self._emits_after_close += 1
                if counted and owner is not None:
                    rejected.setdefault(id(owner), [owner, 0])[1] += 1
                continue
            owner = sub.owner_ref()
            if owner is None:
                # Владелец собран без close: доставки нет, она считается.
                with self._lock:
                    self._store.pop(sub.seq, None)
                    self._emits_after_close += 1
                    first = not self._warned_collected
                    self._warned_collected = True
                if first:
                    _log.warning(
                        "Subscribers '%s': владелец %s собран без close — доставка отклонена", self._name, sub.path
                    )
                continue
            del owner
            try:
                sub.cb(*args, **kwargs)
            except Exception as exc:
                text = f"{type(exc).__name__}: {exc}"
                with self._lock:
                    self._error_count += 1
                    logged = len(self._errors) < _ERRORS_CAP
                    if logged:
                        self._errors.append((sub.path, text))
                if logged:
                    _log.warning("Subscribers '%s': подписчик %s бросил %s", self._name, sub.path, text)
            else:
                delivered += 1
        for owner, n in rejected.values():
            owner.note_emits_after_close(n)
        return delivered
