# -*- coding: utf-8 -*-
"""SectionProtocol — единый контракт секции для вкладок с tree-навигацией.

Секция — логическая единица контента внутри таба (например, «Настройки системы»,
«Оформление», «История»). Presenter таба работает с секциями через этот Protocol,
не зная их конкретных реализаций.

В модуле определены два Protocol:

`SectionProtocol`
    Обязательный минимум: `key`, `title`, `widget`, `action_buttons`,
    `on_activated`, `on_deactivated`. Любая секция должна его удовлетворять.

`SectionWithEvents`
    Опциональный mixin для секций, которые умеют эмитить события наружу
    (dirty-флаг, успешное сохранение) через Qt-сигналы и/или подписываться
    на ActionBus. `BaseTreeNavTab` проверяет наличие атрибутов через
    `getattr(section, "section_dirty_changed", None)` и подключается
    автоматически. Существующие секции, не реализующие этот контракт,
    продолжают работать без изменений.

Использование::

    class MySection:
        @property
        def key(self) -> str: return "my_section"
        @property
        def title(self) -> str: return "Моя секция"
        def widget(self) -> QWidget: return self._widget
        def action_buttons(self) -> list[QWidget]: return [self._btn]
        def on_activated(self) -> None: ...
        def on_deactivated(self) -> None: ...

См. ADR-126.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.core.qt_imports import (
        SignalInstance,
        QWidget,
    )


@runtime_checkable
class SectionProtocol(Protocol):
    """Контракт секции для вкладок с tree-навигацией.

    Атрибуты:
        key:   уникальный строковый идентификатор (для маппинга в nav-tree и content stack)
        title: отображаемое название (для UI)

    Методы:
        widget():          корневой QWidget секции
        action_buttons():  список кнопок для action-колонки (пустой если нет)
        on_activated():    вызывается при переключении на эту секцию
        on_deactivated():  вызывается при уходе с этой секции
    """

    @property
    def key(self) -> str: ...

    @property
    def title(self) -> str: ...

    def widget(self) -> QWidget: ...

    def action_buttons(self) -> list[QWidget]: ...

    def on_activated(self) -> None: ...

    def on_deactivated(self) -> None: ...


@runtime_checkable
class SectionWithEvents(Protocol):
    """Опциональный mixin: секция эмитит события и/или подписывается на ActionBus.

    Этот Protocol проверяется фреймворком через `isinstance` (он
    `@runtime_checkable`) или через `getattr(section, "section_dirty_changed",
    None)`. Реализация полностью опциональна — секция без этих атрибутов
    остаётся валидной по `SectionProtocol`.

    Атрибуты:
        section_dirty_changed: Qt-сигнал `Signal(bool)` — эмитится при смене
                               dirty-флага. `BaseTreeNavTab` транслирует его
                               наружу как `tab.section_dirty_changed(key, dirty)`.
        section_data_saved:    Qt-сигнал `Signal(dict)` — эмитится при успешном
                               сохранении данных секции. Транслируется как
                               `tab.section_data_saved(key, data)`.

    Методы:
        bus_change_callback(): возвращает `Callable[[], None]` для подписки
                               на ActionBus (или `None`, если секция не нуждается
                               в уведомлениях шины). `BaseTreeNavTab` вызывает
                               этот метод после создания секции.
    """

    section_dirty_changed: Optional["SignalInstance"]
    section_data_saved: Optional["SignalInstance"]

    def bus_change_callback(self) -> Optional[Callable[[], None]]: ...
