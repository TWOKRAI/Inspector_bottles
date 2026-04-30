"""base.py — Базовый класс middleware и MiddlewarePipeline.

Middleware вставляется между IPC-обработчиком и TreeStore.
Позволяет валидировать, модифицировать или отклонять изменения,
а также реагировать на успешные записи (логирование, метрики и т.д.).

Порядок вызова: первый зарегистрированный → первый вызванный.
Пустой pipeline — нулевой overhead (проверка `if self._middlewares:`).
Потокобезопасность НЕ нужна — StateStoreManager однопоточный.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from state_store.core.delta import Delta

logger = logging.getLogger(__name__)


class StateMiddleware(ABC):
    """Базовый класс middleware для StateStore.

    Наследники переопределяют нужные хуки (before_set, after_set и т.д.).
    Неиспользуемые хуки оставляют по умолчанию — они пропускают данные без изменений.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Уникальное имя middleware (для remove и логирования)."""
        ...

    # --- set ---

    def before_set(self, path: str, value: Any, source: str, context: dict) -> tuple[bool, Any]:
        """Вызывается перед TreeStore.set().

        Args:
            path: путь в дереве.
            value: устанавливаемое значение.
            source: источник изменения.
            context: общий dict, передаётся от before_* к after_*.

        Returns:
            (proceed, modified_value):
                proceed=False → цепочка прерывается, операция отклонена.
                modified_value → значение, которое увидит следующий middleware / TreeStore.
        """
        return True, value

    def after_set(self, delta: Delta, context: dict) -> None:
        """Вызывается после успешного TreeStore.set().

        Args:
            delta: результирующая дельта.
            context: общий dict (тот же, что был передан в before_set).
        """

    # --- merge ---

    def before_merge(self, path: str, data: dict, source: str, context: dict) -> tuple[bool, dict]:
        """Вызывается перед TreeStore.merge().

        Returns:
            (proceed, modified_data):
                proceed=False → цепочка прерывается, операция отклонена.
                modified_data → данные, которые увидит следующий middleware / TreeStore.
        """
        return True, data

    def after_merge(self, deltas: list[Delta], context: dict) -> None:
        """Вызывается после успешного TreeStore.merge().

        Args:
            deltas: список дельт от merge.
            context: общий dict (тот же, что был передан в before_merge).
        """

    # --- delete ---

    def before_delete(self, path: str, source: str, context: dict) -> tuple[bool]:
        """Вызывается перед TreeStore.delete().

        Returns:
            (proceed,): proceed=False → операция отклонена.
        """
        return (True,)

    def after_delete(self, delta: Delta, context: dict) -> None:
        """Вызывается после успешного TreeStore.delete().

        Args:
            delta: результирующая дельта удаления.
            context: общий dict.
        """


class MiddlewarePipeline:
    """Цепочка middleware. Порядок: первый зарегистрированный → первый вызванный.

    Пустой pipeline — нулевой overhead: все run_* методы проверяют
    `if not self._middlewares:` и возвращают результат без итерации.
    """

    def __init__(self) -> None:
        self._middlewares: list[StateMiddleware] = []

    def use(self, middleware: StateMiddleware) -> None:
        """Добавить middleware в конец цепочки.

        Args:
            middleware: экземпляр StateMiddleware.

        Raises:
            ValueError: если middleware с таким именем уже зарегистрирован.
        """
        for existing in self._middlewares:
            if existing.name == middleware.name:
                raise ValueError(f"Middleware с именем '{middleware.name}' уже зарегистрирован")
        self._middlewares.append(middleware)

    def remove(self, name: str) -> bool:
        """Удалить middleware по имени.

        Args:
            name: имя middleware.

        Returns:
            True если middleware был найден и удалён, False иначе.
        """
        for i, mw in enumerate(self._middlewares):
            if mw.name == name:
                self._middlewares.pop(i)
                return True
        return False

    # --- run_before / run_after для set ---

    def run_before_set(self, path: str, value: Any, source: str) -> tuple[bool, Any, dict]:
        """Прогнать before_set через все middleware по порядку.

        Args:
            path: путь в дереве.
            value: устанавливаемое значение.
            source: источник изменения.

        Returns:
            (proceed, value, context):
                proceed — True если все middleware разрешили операцию.
                value — (возможно модифицированное) значение.
                context — общий dict для передачи в run_after_set.
        """
        context: dict = {}
        if not self._middlewares:
            return True, value, context

        for mw in self._middlewares:
            proceed, value = mw.before_set(path, value, source, context)
            if not proceed:
                return False, value, context

        return True, value, context

    def run_after_set(self, delta: Delta, context: dict) -> None:
        """Прогнать after_set через все middleware по порядку.

        Args:
            delta: результирующая дельта.
            context: общий dict из run_before_set.
        """
        if not self._middlewares:
            return

        for mw in self._middlewares:
            mw.after_set(delta, context)

    # --- run_before / run_after для merge ---

    def run_before_merge(self, path: str, data: dict, source: str) -> tuple[bool, dict, dict]:
        """Прогнать before_merge через все middleware по порядку.

        Returns:
            (proceed, data, context).
        """
        context: dict = {}
        if not self._middlewares:
            return True, data, context

        for mw in self._middlewares:
            proceed, data = mw.before_merge(path, data, source, context)
            if not proceed:
                return False, data, context

        return True, data, context

    def run_after_merge(self, deltas: list[Delta], context: dict) -> None:
        """Прогнать after_merge через все middleware по порядку."""
        if not self._middlewares:
            return

        for mw in self._middlewares:
            mw.after_merge(deltas, context)

    # --- run_before / run_after для delete ---

    def run_before_delete(self, path: str, source: str) -> tuple[bool, dict]:
        """Прогнать before_delete через все middleware по порядку.

        Returns:
            (proceed, context).
        """
        context: dict = {}
        if not self._middlewares:
            return True, context

        for mw in self._middlewares:
            (proceed,) = mw.before_delete(path, source, context)
            if not proceed:
                return False, context

        return True, context

    def run_after_delete(self, delta: Delta, context: dict) -> None:
        """Прогнать after_delete через все middleware по порядку."""
        if not self._middlewares:
            return

        for mw in self._middlewares:
            mw.after_delete(delta, context)

    # --- Утилиты ---

    @property
    def is_empty(self) -> bool:
        """True если pipeline не содержит ни одного middleware."""
        return len(self._middlewares) == 0
