"""Логика вкладки плагинов без привязки к Qt (кроме вызовов через view)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models.plugin_manager_model import PluginManagerModel
    from .view import PluginManagerViewProtocol

_logger = logging.getLogger(__name__)


class PluginManagerPresenter:
    """Презентер вкладки управления плагинами (MVP).

    Содержит всю бизнес-логику взаимодействия пользователя с каталогом
    плагинов. Не зависит от Qt напрямую — общается с UI через PluginManagerViewProtocol.
    """

    def __init__(
        self,
        *,
        view: PluginManagerViewProtocol,
        model: PluginManagerModel,
    ) -> None:
        """Инициализировать презентер.

        Args:
            view: реализация PluginManagerViewProtocol (виджет).
            model: модель данных плагинов.
        """
        self._view = view
        self._model = model

    # ------------------------------------------------------------------
    # Методы обработки событий пользователя
    # ------------------------------------------------------------------

    def on_init(self) -> None:
        """Начальная загрузка данных при создании вкладки."""
        self._refresh()

    def on_plugin_selected(self, plugin_name: str) -> None:
        """Пользователь выбрал плагин в таблице.

        Args:
            plugin_name: имя выбранного плагина.
        """
        detail = self._model.get_plugin_detail(plugin_name)
        if detail:
            self._view.show_plugin_detail(detail)
        else:
            self._view.clear_detail()

    def on_plugin_enabled_changed(self, plugin_name: str, enabled: bool) -> None:
        """Пользователь переключил checkbox enabled/disabled.

        Args:
            plugin_name: имя плагина.
            enabled: новое состояние чекбокса.
        """
        self._model.set_enabled(plugin_name, enabled)
        # Обновляем таблицу чтобы отразить изменение (модель сама эмитит plugins_updated,
        # но явный refresh нужен если сигнал не подключён)
        self._refresh()

    def on_reload_requested(self) -> None:
        """Кнопка 'Обновить плагины'."""
        result = self._model.reload_plugins()
        if result is not None:
            # PluginDiscoveryResult имеет поля loaded, failed, new_plugins
            loaded = getattr(result, "loaded", [])
            failed = getattr(result, "failed", [])
            new_plugins = getattr(result, "new_plugins", [])
            self._view.set_status_text(
                f"Загружено: {len(loaded)}, ошибок: {len(failed)}, "
                f"новых: {len(new_plugins)}"
            )
        else:
            self._view.set_status_text("PluginManager не подключён")
        self._refresh()

    def on_filter_changed(self) -> None:
        """Пользователь изменил фильтр или поиск."""
        self._refresh()

    def on_default_config_changed(self, plugin_name: str, config: dict) -> None:
        """Пользователь сохранил дефолтную конфигурацию плагина.

        Args:
            plugin_name: имя плагина.
            config: словарь конфигурации.
        """
        self._model.set_default_config(plugin_name, config)
        self._view.set_status_text(f"Конфигурация '{plugin_name}' сохранена")

    def on_model_updated(self) -> None:
        """Модель уведомила об обновлении данных."""
        self._refresh()

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        """Обновить таблицу с учётом текущего фильтра."""
        category, search = self._view.get_current_filter()
        plugins = self._model.filter_plugins(category, search)
        self._view.refresh_table(plugins)
        self._view.set_status_text(f"Плагинов: {len(plugins)}")
        _logger.debug(
            "Таблица плагинов обновлена: %d записей (категория=%s, поиск='%s')",
            len(plugins),
            category,
            search,
        )
