"""BaseEditorModel — абстрактная модель данных редактора (без UI).

Паттерн взят из GraphEditorModel, обобщён до универсальной основы
для любых SchemaBase-items.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable


class BaseEditorModel:
    """Базовая модель данных редактора.

    Хранит dict-представления SchemaBase-объектов, предоставляет мутации.
    Каждая мутация возвращает (old, new) для undo.
    Нет зависимостей от Qt — чистая бизнес-логика.
    """

    def __init__(self) -> None:
        # Хранилище элементов: key → dict-представление SchemaBase
        self._items: dict[str, Any] = {}
        # Snapshot для dirty tracking (deepcopy на момент вызова snapshot())
        self._snapshot: dict | None = None
        # Callbacks, вызываемые после каждой мутации (не Qt Signal)
        self._on_changed: list[Callable] = []

    # ------------------------------------------------------------------
    # Загрузка и snapshot
    # ------------------------------------------------------------------

    def load(self, items: dict[str, Any]) -> None:
        """Загрузить данные (заменить _items целиком).

        Args:
            items: словарь key → dict-представление SchemaBase.
        """
        self._items = dict(items)
        self._notify()

    def snapshot(self) -> None:
        """Сохранить deepcopy текущего состояния в _snapshot.

        После вызова dirty вернёт False (если нет дальнейших мутаций).
        """
        self._snapshot = deepcopy(self._items)

    def mark_clean(self) -> None:
        """Сделать текущее состояние «чистым» (вызывает snapshot())."""
        self.snapshot()

    # ------------------------------------------------------------------
    # Dirty tracking
    # ------------------------------------------------------------------

    @property
    def dirty(self) -> bool:
        """True если _items отличается от последнего snapshot.

        Возвращает True если snapshot ещё не был сделан.
        """
        if self._snapshot is None:
            return True
        return self._items != self._snapshot

    # ------------------------------------------------------------------
    # Чтение
    # ------------------------------------------------------------------

    @property
    def items(self) -> dict[str, Any]:
        """Копия текущего хранилища элементов."""
        return dict(self._items)

    # ------------------------------------------------------------------
    # Мутации (возвращают (old, new) для undo)
    # ------------------------------------------------------------------

    def add_item(self, key: str, item: Any) -> tuple[None, Any]:
        """Добавить элемент в хранилище.

        Args:
            key: ключ элемента.
            item: dict-представление SchemaBase.

        Returns:
            (None, item) — old_state = None (элемента не было).
        """
        self._items[key] = item
        self._notify()
        return (None, item)

    def remove_item(self, key: str) -> tuple[Any, None]:
        """Удалить элемент из хранилища.

        Args:
            key: ключ элемента.

        Returns:
            (удалённый элемент, None).

        Raises:
            KeyError: если ключ не найден.
        """
        if key not in self._items:
            raise KeyError(f"Элемент '{key}' не найден")
        removed = self._items.pop(key)
        self._notify()
        return (removed, None)

    def modify_item(
        self,
        key: str,
        fields: dict[str, Any],
    ) -> tuple[dict, dict]:
        """Обновить поля элемента (только изменённые ключи).

        Args:
            key: ключ элемента.
            fields: словарь {имя_поля: новое_значение}.

        Returns:
            (old_fields, new_fields) — только ключи из fields.

        Raises:
            KeyError: если ключ не найден.
        """
        if key not in self._items:
            raise KeyError(f"Элемент '{key}' не найден")

        item = self._items[key]

        # Сохраняем старые значения только изменяемых ключей
        old_fields: dict[str, Any] = {k: deepcopy(item.get(k)) for k in fields}

        # Применяем новые значения
        item.update(fields)

        new_fields: dict[str, Any] = {k: deepcopy(item[k]) for k in fields}

        self._notify()
        return (old_fields, new_fields)

    # ------------------------------------------------------------------
    # Валидация (template method — подклассы переопределяют)
    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        """Валидация данных модели.

        Returns:
            Список строк с ошибками (пустой список = всё ок).
            Подклассы переопределяют для добавления конкретных проверок.
        """
        return []

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def add_change_callback(self, fn: Callable) -> None:
        """Добавить callback, вызываемый после каждой мутации.

        Args:
            fn: callable без аргументов.
        """
        self._on_changed.append(fn)

    def _notify(self) -> None:
        """Вызвать все зарегистрированные callbacks."""
        for fn in self._on_changed:
            fn()
