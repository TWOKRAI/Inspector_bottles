# -*- coding: utf-8 -*-
"""TreeNavTabPresenter — универсальный презентер вкладки с tree-навигацией.

Унифицированная база для вкладок типа Settings/Recipes/Processes:
владеет реестром секций (`SectionProtocol`), индексами content/action
стеков, навигацией по дереву и ленивым созданием узлов. Не импортирует
Qt — `view` подаётся duck-типом через методы (`set_content_index`,
`set_action_index`, `select_tree_key`, `create_lazy_section`).

Подкласс (например, `SettingsPresenter`) добавляет:
* конкретный набор секций (явный список ключей или `list[SectionSpec]`),
* реализацию `populate()` (что вызвать у view, чтобы построить страницы),
* app-specific обработку шин/undo/redo через свой контекст.

Pure-Python: модуль работает без PySide6.

См. ADR-126.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from .mvp_pattern import TabPresenterBase, TView, TUi

if TYPE_CHECKING:
    from .section_protocol import SectionProtocol

logger = logging.getLogger(__name__)


class TreeNavTabPresenter(TabPresenterBase[TView, TUi]):
    """Универсальный презентер для вкладки с tree-навигацией.

    Отвечает за:
    * реестр секций (`SectionProtocol` по ключу);
    * маппинги ключ → индекс в content/action `QStackedWidget` (хранит
      индексы; сами стеки живут в view);
    * ленивые секции — узлы, чья инициализация откладывается до первой
      активации (см. `register_lazy_section` / `ensure_lazy_section`);
    * навигацию: переключение `content_stack`, `action_stack`, активация
      и деактивация секций через `on_activated` / `on_deactivated`.

    Все вызовы UI идут через `self._view` (duck-typed): подкласс/тест может
    подсунуть любой объект с нужными методами.
    """

    def __init__(
        self,
        *,
        view: TView,
        rm=None,
        ui: TUi = None,
    ) -> None:
        super().__init__(view=view, rm=rm, ui=ui)

        # Реестр зарегистрированных секций (key → SectionProtocol)
        self._sections: dict[str, "SectionProtocol"] = {}

        # Текущий активный ключ секции
        self._current_key: Optional[str] = None

        # Маппинги ключ → индекс в content/action stack
        self._page_index: dict[str, int] = {}
        self._action_page_index: dict[str, int] = {}

        # Ленивые секции: key зарегистрирован, но виджет ещё не создан
        # (None — не создана; иначе — виджет).
        self._lazy_sections: dict[str, object | None] = {}

    # ------------------------------------------------------------------
    # Реестр секций
    # ------------------------------------------------------------------

    def register_section(self, section: "SectionProtocol") -> None:
        """Зарегистрировать секцию в реестре презентера."""
        self._sections[section.key] = section
        logger.debug("Секция зарегистрирована: %s (%s)", section.key, section.title)

    def section(self, key: str) -> Optional["SectionProtocol"]:
        """Получить секцию по ключу (или `None`, если не зарегистрирована)."""
        return self._sections.get(key)

    # ------------------------------------------------------------------
    # Регистрация страниц content/action stack
    # ------------------------------------------------------------------

    def register_content_page(self, key: str, index: int) -> None:
        """Сохранить индекс страницы content stack для ключа."""
        self._page_index[key] = index

    def register_action_page(self, key: str, index: int) -> None:
        """Сохранить индекс страницы action stack для ключа."""
        self._action_page_index[key] = index

    # ------------------------------------------------------------------
    # Ленивые секции (узлы, инициализируемые при первой активации)
    # ------------------------------------------------------------------

    def register_lazy_section(self, key: str) -> None:
        """Объявить ключ как ленивую секцию (виджет создаст view по запросу)."""
        self._lazy_sections[key] = None

    def is_lazy_section(self, key: str) -> bool:
        """`True`, если ключ — ленивая секция, ещё не созданная."""
        return key in self._lazy_sections and key not in self._page_index

    def ensure_lazy_section(self, key: str) -> None:
        """Если секция ленивая и не создана — попросить view её создать.

        View создаёт Qt-виджет и вызывает `notify_lazy_section_created()`
        для обратной регистрации индексов.
        """
        if self.is_lazy_section(key):
            self._view.create_lazy_section(key)

    def notify_lazy_section_created(self, key: str, widget: object, action_idx: int, content_idx: int) -> None:
        """Уведомить презентер о создании ленивой секции и сохранить индексы."""
        self._lazy_sections[key] = widget
        self._page_index[key] = content_idx
        self._action_page_index[key] = action_idx

    # ------------------------------------------------------------------
    # Навигация
    # ------------------------------------------------------------------

    def on_tree_item_changed(self, key: str) -> None:
        """Обработать смену активного элемента дерева навигации.

        Логика:
        1. Деактивировать предыдущую секцию (`on_deactivated`).
        2. Если новая секция ленивая — попросить view её создать.
        3. Переключить content stack и action stack через view.
        4. Активировать новую секцию (`on_activated`).
        """
        if not key:
            return

        # Деактивировать предыдущую секцию
        prev_key = self._current_key
        if prev_key and prev_key in self._sections:
            try:
                self._sections[prev_key].on_deactivated()
            except Exception:
                logger.exception("Ошибка on_deactivated для секции %s", prev_key)

        self._current_key = key

        # Ленивое создание секций (через view)
        self.ensure_lazy_section(key)

        # Переключить content stack
        idx = self._page_index.get(key)
        if idx is not None:
            self._view.set_content_index(idx)

        # Переключить action stack
        self._switch_action_buttons(key)

        # Активировать новую секцию
        if key in self._sections:
            try:
                self._sections[key].on_activated()
            except Exception:
                logger.exception("Ошибка on_activated для секции %s", key)

    def navigate_to(self, key: str) -> None:
        """Навигировать к секции: выбрать элемент в дереве через view."""
        self._view.select_tree_key(key)

    # ------------------------------------------------------------------
    # Action-колонка
    # ------------------------------------------------------------------

    def _switch_action_buttons(self, key: str) -> None:
        """Переключить action stack на страницу текущей секции."""
        empty_idx = self._action_page_index.get("_empty", 0)
        idx = self._action_page_index.get(key, empty_idx)
        self._view.set_action_index(idx)

    def get_action_index(self, key: str) -> int:
        """Получить индекс action-страницы по ключу (публичный аксессор)."""
        empty_idx = self._action_page_index.get("_empty", 0)
        return self._action_page_index.get(key, empty_idx)

    # ------------------------------------------------------------------
    # Аксессоры
    # ------------------------------------------------------------------

    @property
    def current_key(self) -> Optional[str]:
        """Текущий активный ключ секции."""
        return self._current_key
