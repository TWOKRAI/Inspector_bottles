"""TabFactory — фабрика табов с ленивой инициализацией и заглушками.

Использование:
    factory = TabFactory(ctx, custom_factories={"settings": my_settings_factory})
    factory.create_tabs(tab_widget)

custom_factories: dict[tab_id -> Callable[[AppContext], QWidget]]
    Если id отсутствует — создаётся PlaceholderTab.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from .widgets.tabs.placeholder import PlaceholderTab

if TYPE_CHECKING:
    from .app_context import AppContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Порядок и метаданные всех табов приложения
# ---------------------------------------------------------------------------

TAB_ORDER: list[dict] = [
    {"id": "settings",  "title": "Settings",  "description": "Администрирование, конфиг системы"},
    {"id": "recipes",   "title": "Recipes",   "description": "Пресеты/рецепты обработки"},
    {"id": "processes", "title": "Processes", "description": "Управление процессами"},
    {"id": "services",  "title": "Services",  "description": "Камеры SDK, БД, робот, нейронки"},
    {"id": "plugins",   "title": "Plugins",   "description": "Обработка изображений, мосты"},
    {"id": "pipeline",  "title": "Pipeline",  "description": "Визуальный конструктор цепочек"},
    {"id": "displays",  "title": "Displays",  "description": "Управление экранами вывода"},
]


# ---------------------------------------------------------------------------
# LazyTabWidget — обёртка для ленивой инициализации
# ---------------------------------------------------------------------------


class LazyTabWidget(QWidget):
    """Обёртка для ленивой инициализации таба.

    Содержимое создаётся при первом событии showEvent.
    До этого показывает метку "Loading...".
    """

    def __init__(
        self,
        factory_fn: Callable[[], QWidget],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._factory_fn = factory_fn
        self._initialized = False

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        # Временная метка до первого показа
        self._loading_label = QLabel("Loading...")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._loading_label)

    def showEvent(self, event) -> None:  # type: ignore[override]
        """Инициализировать содержимое при первом показе."""
        super().showEvent(event)
        if not self._initialized:
            self._initialized = True
            self._loading_label.deleteLater()
            self._loading_label = None  # type: ignore[assignment]
            try:
                widget = self._factory_fn()
                if widget is not None:
                    self._layout.addWidget(widget)
            except Exception:
                logger.exception("Ошибка создания таба")
                # Fallback — показываем метку об ошибке
                err_label = QLabel("Ошибка загрузки")
                err_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._layout.addWidget(err_label)


# ---------------------------------------------------------------------------
# TabFactory
# ---------------------------------------------------------------------------


class TabFactory:
    """Фабрика табов с поддержкой custom factories и ленивой инициализации.

    Args:
        ctx: AppContext — DI-контейнер, передаётся в custom factory
        custom_factories: опциональный dict[tab_id -> factory(ctx) -> QWidget]
            Если передан factory для tab_id, таб создаётся через LazyTabWidget.
            Иначе используется PlaceholderTab.
    """

    def __init__(
        self,
        ctx: "AppContext",
        custom_factories: dict[str, Callable] | None = None,
    ) -> None:
        self._ctx = ctx
        self._custom_factories: dict[str, Callable] = custom_factories or {}

    def create_tabs(self, tab_widget: QTabWidget) -> None:
        """Создать все табы согласно TAB_ORDER и добавить в QTabWidget.

        Табы с custom_factories — LazyTabWidget (создаются при первом показе).
        Остальные — PlaceholderTab (создаются немедленно, они лёгкие).
        """
        for tab_info in TAB_ORDER:
            tab_id = tab_info["id"]
            title = tab_info["title"]

            if tab_id in self._custom_factories:
                # Ленивая инициализация: factory вызывается только при первом show
                factory_fn = self._custom_factories[tab_id]
                widget: QWidget = LazyTabWidget(
                    lambda fn=factory_fn: fn(self._ctx)
                )
            else:
                # Заглушка — создаётся сразу (лёгкий виджет)
                widget = PlaceholderTab(
                    tab_id=tab_id,
                    title=title,
                    description=tab_info.get("description", ""),
                )

            tab_widget.addTab(widget, title)

    def create_tab(self, tab_id: str) -> QWidget | None:
        """Создать один таб по id.

        Если tab_id неизвестен — вернуть None.
        Если custom factory есть — вызвать напрямую (без LazyTabWidget).
        При ошибке factory или возврате None — использовать PlaceholderTab.
        """
        tab_info = next((t for t in TAB_ORDER if t["id"] == tab_id), None)
        if tab_info is None:
            return None

        if tab_id in self._custom_factories:
            try:
                result = self._custom_factories[tab_id](self._ctx)
                return result if result is not None else self._make_placeholder(tab_info)
            except Exception:
                logger.exception("Ошибка создания таба %s", tab_id)
                return self._make_placeholder(tab_info)

        return self._make_placeholder(tab_info)

    @staticmethod
    def _make_placeholder(tab_info: dict) -> PlaceholderTab:
        """Создать PlaceholderTab из метаданных таба."""
        return PlaceholderTab(
            tab_id=tab_info["id"],
            title=tab_info["title"],
            description=tab_info.get("description", ""),
        )
