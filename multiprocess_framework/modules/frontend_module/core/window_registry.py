# -*- coding: utf-8 -*-
"""
WindowRegistry — реестр окон и фабрика для их создания.

Регистрирует фабрики по имени окна. Поддерживает singleton-режим.
Расширенные флаги: needs_fullscreen, needs_cursor, needs_access_level, auto_close.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class WindowEntry:
    """
    Запись окна в реестре.

    Attributes:
        factory: Функция создания окна (**kwargs) -> QWidget
        singleton: True = создать один раз, потом возвращать тот же инстанс
        needs_fullscreen: Участвует в глобальном set_fullscreen?
        needs_cursor: Участвует в глобальном toggle_cursor?
        needs_access_level: Получает уведомления об изменении access_level?
        auto_close: Автозакрытие через N секунд (0 = отключено)
    """

    factory: Callable[..., Any]
    singleton: bool = True
    needs_fullscreen: bool = True
    needs_cursor: bool = True
    needs_access_level: bool = True
    auto_close: int = 0
    instance: Optional[Any] = field(default=None, repr=False)
    created: bool = field(default=False, repr=False)


class WindowRegistry:
    """
    Реестр окон с фабриками.

    Пример:
        registry = WindowRegistry()
        registry.register("main", lambda **kw: MainWindow(**kw))
        registry.register("loading", create_loading_window, singleton=True)
        w = registry.create("main", title="Inspector", width=1280)
    """

    def __init__(self) -> None:
        self._entries: Dict[str, WindowEntry] = {}
        self._order: List[str] = []

    def register(
        self,
        name: str,
        factory: Callable[..., Any],
        *,
        singleton: bool = True,
        needs_fullscreen: bool = True,
        needs_cursor: bool = True,
        needs_access_level: bool = True,
        auto_close: int = 0,
    ) -> "WindowRegistry":
        """
        Зарегистрировать окно. Chainable.

        Args:
            name: Уникальное имя окна
            factory: Функция (**kwargs) -> окно
            singleton: True = один инстанс на всё приложение
            needs_fullscreen: Участвует в set_fullscreen?
            needs_cursor: Участвует в toggle_cursor?
            needs_access_level: Получает update_access_level?
            auto_close: Автозакрытие через N секунд (0 = отключено)
        """
        if name in self._entries:
            raise ValueError(f"Window '{name}' already registered")
        self._entries[name] = WindowEntry(
            factory=factory,
            singleton=singleton,
            needs_fullscreen=needs_fullscreen,
            needs_cursor=needs_cursor,
            needs_access_level=needs_access_level,
            auto_close=auto_close,
        )
        self._order.append(name)
        return self

    def create(self, name: str, **kwargs: Any) -> Optional[Any]:
        """
        Создать окно по имени.

        Returns:
            Окно или None (если не зарегистрировано)
        """
        entry = self._entries.get(name)
        if not entry:
            return None
        if entry.singleton and entry.created and entry.instance is not None:
            return entry.instance
        entry.instance = entry.factory(**kwargs)
        entry.created = True
        return entry.instance

    def get(self, name: str) -> Optional[Any]:
        """Получить созданный инстанс (или None)."""
        entry = self._entries.get(name)
        return entry.instance if entry else None

    def is_created(self, name: str) -> bool:
        """Создано ли окно."""
        entry = self._entries.get(name)
        return entry.created if entry else False

    def get_entry(self, name: str) -> Optional[WindowEntry]:
        """Получить конфигурацию окна."""
        return self._entries.get(name)

    def list_windows(self) -> List[str]:
        """Список зарегистрированных окон."""
        return list(self._order)

    def all_names(self) -> List[str]:
        """Все зарегистрированные имена (алиас list_windows)."""
        return list(self._order)

    def created_names(self) -> List[str]:
        """Имена созданных окон."""
        return [n for n in self._order if self._entries[n].created]

    def filter_names(
        self,
        *,
        needs_fullscreen: Optional[bool] = None,
        needs_cursor: Optional[bool] = None,
        needs_access_level: Optional[bool] = None,
        created_only: bool = True,
    ) -> List[str]:
        """Фильтрация имён по критериям."""
        result = []
        for name in self._order:
            entry = self._entries[name]
            if created_only and not entry.created:
                continue
            if needs_fullscreen is not None and entry.needs_fullscreen != needs_fullscreen:
                continue
            if needs_cursor is not None and entry.needs_cursor != needs_cursor:
                continue
            if needs_access_level is not None and entry.needs_access_level != needs_access_level:
                continue
            result.append(name)
        return result

    def apply(self, names: List[str], action: Callable[[Any], None]) -> None:
        """Применить действие к списку окон."""
        for name in names:
            entry = self._entries.get(name)
            if entry and entry.instance:
                action(entry.instance)

    def close_all(self) -> None:
        """Закрыть все окна и очистить инстансы."""
        for entry in self._entries.values():
            if entry.instance:
                try:
                    if hasattr(entry.instance, "close"):
                        entry.instance.close()
                    if hasattr(entry.instance, "deleteLater"):
                        entry.instance.deleteLater()
                except Exception:
                    pass
                entry.instance = None
            entry.created = False
