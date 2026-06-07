# -*- coding: utf-8 -*-
"""PreviewWindowManager — реестр открытых окон превью дисплеев.

Хранит маппинг display_id → PreviewWindow. Используется presenter'ом при
смене рецепта (RecipeActivated) для реализации варианта А (раздел 11.4 спеки):
  - orphan-окна (id отсутствует в новом рецепте) → закрываются;
  - совпадающие id → переподключаются (unsubscribe + subscribe), окно не закрывается.

Жизненный цикл:
  1. ``register(display_id, window)`` — вызывается из tab при открытии превью.
  2. ``apply_recipe_change(new_display_ids)`` — вызывается presenter'ом при RecipeActivated.
  3. ``close_all()`` — вызывается при teardown (вкладка/приложение закрываются).

Refs: plans/displays-in-recipe/plan.md Task 2.3
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiprocess_framework.modules.router_module import RouterManager
    from multiprocess_prototype.frontend.widgets.displays.preview_window import PreviewWindow

_logger = logging.getLogger(__name__)


class PreviewWindowManager:
    """Реестр открытых окон превью: {display_id: PreviewWindow}.

    Реализует вариант А переключения рецепта (раздел 11.4 спеки):
      - orphan-окна закрываются автоматически;
      - совпадающие id переподключаются без закрытия окна.

    Чистый Python, без Qt-импортов на уровне модуля (импортируются lazy внутри методов
    где необходимо для type-checking при вызове Qt API).
    """

    def __init__(self) -> None:
        # Реестр: display_id → PreviewWindow
        self._windows: dict[str, "PreviewWindow"] = {}

    # ------------------------------------------------------------------ #
    #  Регистрация                                                         #
    # ------------------------------------------------------------------ #

    def register(self, display_id: str, window: "PreviewWindow") -> None:
        """Зарегистрировать окно превью в реестре.

        Если для данного display_id уже было открыто окно — старое закрывается,
        новое занимает его место (защита от дублирования через кнопку «Открыть превью»).

        Args:
            display_id: идентификатор дисплея (ключ реестра).
            window:     PreviewWindow для регистрации.
        """
        old = self._windows.get(display_id)
        if old is not None and old is not window:
            _logger.debug("PreviewWindowManager: замена старого окна для '%s'", display_id)
            try:
                old.close()
            except Exception:
                _logger.exception("PreviewWindowManager: ошибка закрытия старого окна '%s'", display_id)
        self._windows[display_id] = window
        _logger.debug("PreviewWindowManager: зарегистрировано окно '%s'", display_id)

    def unregister(self, display_id: str) -> None:
        """Снять регистрацию окна по display_id (без закрытия).

        Вызывается из closeEvent PreviewWindow при ручном закрытии,
        чтобы реестр не хранил битые ссылки.

        Args:
            display_id: идентификатор дисплея.
        """
        if display_id in self._windows:
            del self._windows[display_id]
            _logger.debug("PreviewWindowManager: снята регистрация '%s'", display_id)

    # ------------------------------------------------------------------ #
    #  Переключение рецепта (вариант А, раздел 11.4 спеки)               #
    # ------------------------------------------------------------------ #

    def apply_recipe_change(
        self,
        new_display_ids: set[str],
        router_manager: "RouterManager | None" = None,
    ) -> None:
        """Обработать смену рецепта согласно варианту А.

        Алгоритм:
          1. Определить orphan-id (были в реестре, нет в new_display_ids).
          2. Orphan-окна: отписать + закрыть.
          3. Совпадающие id: переподписать (unsubscribe → subscribe).
          4. Удалить orphan из реестра.

        Args:
            new_display_ids: множество display_id активного рецепта
                             (из DisplayCatalog после reload).
            router_manager:  RouterManager для переподписки (None → subscribe no-op).
        """
        current_ids = set(self._windows.keys())
        orphan_ids = current_ids - new_display_ids
        matching_ids = current_ids & new_display_ids

        # Шаг 2: закрыть orphan-окна
        for did in orphan_ids:
            window = self._windows.pop(did, None)
            if window is None:
                continue
            _logger.info("PreviewWindowManager: orphan-окно '%s' закрывается", did)
            try:
                window.unsubscribe()
                window.close()
            except Exception:
                _logger.exception("PreviewWindowManager: ошибка при закрытии orphan '%s'", did)

        # Шаг 3: переподписать совпадающие окна
        for did in matching_ids:
            window = self._windows.get(did)
            if window is None:
                continue
            _logger.info("PreviewWindowManager: переподключение окна '%s' к новому рецепту", did)
            try:
                window.unsubscribe()
                window.subscribe(router_manager)
            except Exception:
                _logger.exception("PreviewWindowManager: ошибка переподписки '%s'", did)

    # ------------------------------------------------------------------ #
    #  Teardown                                                            #
    # ------------------------------------------------------------------ #

    def close_all(self) -> None:
        """Закрыть все зарегистрированные окна превью (teardown).

        Вызывается при закрытии вкладки или приложения.
        """
        for did, window in list(self._windows.items()):
            try:
                window.unsubscribe()
                window.close()
            except Exception:
                _logger.exception("PreviewWindowManager: ошибка закрытия окна '%s'", did)
        self._windows.clear()
        _logger.debug("PreviewWindowManager: все окна закрыты")

    # ------------------------------------------------------------------ #
    #  Интроспекция                                                        #
    # ------------------------------------------------------------------ #

    def is_open(self, display_id: str) -> bool:
        """Проверить, открыто ли окно для данного display_id.

        Args:
            display_id: идентификатор дисплея.

        Returns:
            True если окно зарегистрировано и видимо.
        """
        window = self._windows.get(display_id)
        if window is None:
            return False
        try:
            return window.isVisible()
        except Exception:
            return False

    def open_ids(self) -> set[str]:
        """Вернуть множество display_id с открытыми окнами.

        Returns:
            Множество зарегистрированных display_id (включая невидимые).
        """
        return set(self._windows.keys())

    def __len__(self) -> int:
        return len(self._windows)

    def __contains__(self, display_id: str) -> bool:
        return display_id in self._windows
