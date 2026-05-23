# -*- coding: utf-8 -*-
"""BaseColumnarTab --- nav-агностичная база для вкладок с колоночным layout.

Держит layout (``TabLayoutProtocol``), nav-слот, content_stack и сигнал
``section_changed``. **Не знает** про ``SectionSpec``, ``SectionProtocol``,
``TreeNavTabPresenter`` --- это ответственность подклассов.

Подкласс **обязан** реализовать два хука:

* ``_build_nav_widget() -> QWidget`` --- вернуть виджет навигации
  (QTreeWidget, QListWidget, произвольный QWidget).
* ``_on_nav_changed(key: str) -> None`` --- реагировать на смену выбора.

Переопределяемые хуки:

* ``_create_content_stack() -> QStackedWidget`` --- фабрика стека контента.
  По умолчанию ``QStackedWidget()``. ``BaseTreeNavTab`` переопределяет на
  ``CurrentPageStack()`` для smart-sizing.

Helpers:

* ``register_content_widget(key, widget)`` --- добавить виджет в стек.
* ``select_key(key)`` --- переключить стек на виджет по ключу.

Наследники: ``BaseTreeNavTab``, ``BaseListNavTab`` (Phase 6c).

See also: ADR-126, ADR-127, Phase 6b (plans/tab-template-extraction/plan.md).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    Signal,
)

if TYPE_CHECKING:
    from .tab_layout_protocol import TabLayoutProtocol

logger = logging.getLogger(__name__)


class BaseColumnarTab(QWidget):
    """Nav-агностичная база для вкладок с колоночным layout.

    Подкласс обязан реализовать ``_build_nav_widget()`` и ``_on_nav_changed(key)``.

    Сигналы:
        section_changed(str): имя активного раздела (backward-compat).
    """

    # Имя ``section_changed`` сохранено для backward-compat с потребителями
    section_changed = Signal(str)

    def __init__(
        self,
        *,
        title: str,
        ctx: object,
        layout_factory: "Callable[[], TabLayoutProtocol] | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        """Инициализировать вкладку с колоночным layout.

        Args:
            title:          заголовок (передаётся в layout).
            ctx:            контекст приложения (generic, framework не знает тип).
            layout_factory: фабрика layout'а (TabLayoutProtocol). Обязательна.
            parent:         родительский виджет.
        """
        super().__init__(parent)
        self._ctx = ctx
        self._title = title

        # --- Layout ---
        if layout_factory is None:
            raise RuntimeError(
                "BaseColumnarTab: layout_factory обязателен. "
                "Подкласс должен передать фабрику layout'а, удовлетворяющего "
                "TabLayoutProtocol (например DiffScrollTabLayout).",
            )
        self._tab_layout: "TabLayoutProtocol" = layout_factory()

        # --- Content stack (подкласс может переопределить _create_content_stack) ---
        self._content_stack: QStackedWidget = self._create_content_stack()
        self._key_to_index: dict[str, int] = {}

        # --- Nav widget (подкласс строит) ---
        nav_widget = self._build_nav_widget()
        self._tab_layout.set_nav_widget(nav_widget)

        # --- Content в layout ---
        self._tab_layout.set_content_widget(self._content_stack)

        # --- Title ---
        self._tab_layout.set_title(title)

        # --- Встроить layout в виджет ---
        # Вызывается в конце __init__; подкласс может делать
        # дополнительную настройку _tab_layout (set_action_widget и т.п.)
        # после super().__init__, QVBoxLayout уже содержит _tab_layout.
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        main_layout.addWidget(self._tab_layout)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Переопределяемые хуки
    # ------------------------------------------------------------------

    def _create_content_stack(self) -> QStackedWidget:
        """Фабрика стека контента.

        По умолчанию ``QStackedWidget()``. Подкласс может вернуть
        ``CurrentPageStack()`` для smart-sizing или любой другой подкласс.
        """
        return QStackedWidget()

    # ------------------------------------------------------------------
    # Абстрактные хуки --- подкласс обязан реализовать
    # ------------------------------------------------------------------

    def _build_nav_widget(self) -> QWidget:
        """Построить и вернуть виджет навигации.

        Подкласс возвращает QTreeWidget, QListWidget или произвольный QWidget.
        Вызывается один раз в ``__init__``.

        Note:
            Декоративно-абстрактный метод. ``abc.ABCMeta`` невозможен из-за
            metaclass conflict с ``QWidget`` (Shiboken).
        """
        raise NotImplementedError(f"{type(self).__name__} должен реализовать _build_nav_widget()")

    def _on_nav_changed(self, key: str) -> None:
        """Реагировать на смену выбора в навигации.

        Подкласс реализует логику (ленивое создание, presenter injection и т.п.).
        Вызывается реализациями подкласса в ответ на user-driven навигацию
        (signal handler ``currentItemChanged`` / ``currentRowChanged``).

        **Не** вызывается из ``select_key()`` — это программное переключение
        стека/сигнала. Подкласс сам решает, нужно ли звать ``_on_nav_changed``
        в своём signal handler.

        Note:
            Декоративно-абстрактный метод.
        """
        raise NotImplementedError(f"{type(self).__name__} должен реализовать _on_nav_changed(key)")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def register_content_widget(self, key: str, widget: QWidget) -> int:
        """Добавить виджет в content_stack и запомнить маппинг key -> index.

        Args:
            key:    уникальный ключ виджета.
            widget: виджет для добавления.

        Returns:
            Индекс виджета в стеке.
        """
        index = self._content_stack.addWidget(widget)
        self._key_to_index[key] = index
        return index

    def select_key(self, key: str) -> None:
        """Переключить content_stack на виджет по ключу и эмитить сигнал.

        Args:
            key: ключ зарегистрированного виджета.

        Raises:
            KeyError: если ключ не зарегистрирован.
        """
        if key not in self._key_to_index:
            raise KeyError(
                f"Ключ '{key}' не зарегистрирован в content_stack. Доступные: {list(self._key_to_index.keys())}"
            )
        self._content_stack.setCurrentIndex(self._key_to_index[key])
        self.section_changed.emit(key)
