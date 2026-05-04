"""PluginManagerModel — MVC модель данных для вкладки плагинов.

Агрегирует данные из PluginRegistry и PluginManager.
Все публичные методы возвращают dict/list[dict] (Dict at Boundary).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry

_logger = logging.getLogger(__name__)


class PluginManagerModel(QObject):
    """Модель данных для вкладки управления плагинами.

    Предоставляет плагинам доступ к каталогу (PluginRegistry) и управлению
    загрузкой (PluginManager). Поддерживает фильтрацию, поиск, enable/disable,
    хранение дефолтных конфигураций и кэш метрик.

    Принципы:
    - Dict at Boundary: все публичные методы возвращают только dict/list[dict]
    - Graceful degradation: работает без PluginManager и при пустом Registry
    """

    # Сигнал: данные о плагинах обновились (фильтры, enable/disable, reload)
    plugins_updated = Signal()

    def __init__(self, plugin_manager=None, command_handler=None, parent=None) -> None:
        """Инициализация модели.

        Args:
            plugin_manager: PluginManager | None — для reload/discover.
            command_handler: зарезервировано для IPC (MVP не используется).
            parent: родительский QObject.
        """
        super().__init__(parent)

        # Внешние зависимости
        self._plugin_manager = plugin_manager
        self._command_handler = command_handler  # зарезервировано для IPC

        # Внутреннее состояние
        self._disabled_plugins: set[str] = set()          # отключённые плагины
        self._default_configs: dict[str, dict] = {}        # дефолтные конфигурации
        self._metrics_cache: dict[str, dict] = {}          # кэш метрик (MVP пустой)

    # ------------------------------------------------------------------
    # Публичные методы — Dict at Boundary
    # ------------------------------------------------------------------

    def get_all_plugins(self) -> list[dict]:
        """Вернуть список всех зарегистрированных плагинов.

        Returns:
            list[dict] с полями: name, category, description, class_path,
            inputs (кол-во), outputs (кол-во), enabled, instances, metrics.
        """
        result = []
        try:
            entries = PluginRegistry.list()
        except Exception:
            _logger.exception("Ошибка при получении списка плагинов из PluginRegistry")
            return result

        for entry in entries:
            try:
                plugin_dict = {
                    "name": entry.name,
                    "category": entry.category,
                    "description": entry.description,
                    "class_path": entry.class_path,
                    "inputs": len(entry.inputs),
                    "outputs": len(entry.outputs),
                    "enabled": entry.name not in self._disabled_plugins,
                    "instances": 0,  # MVP: подсчёт инстансов не реализован
                    "metrics": self._metrics_cache.get(entry.name),
                }
                result.append(plugin_dict)
            except Exception:
                _logger.exception("Ошибка при сборке данных плагина '%s'", getattr(entry, "name", "?"))

        return result

    def get_plugin_detail(self, plugin_name: str) -> dict | None:
        """Вернуть расширенные данные о плагине, включая описание портов.

        Args:
            plugin_name: имя плагина в PluginRegistry.

        Returns:
            dict с полями базового плагина + input_ports, output_ports,
            или None если плагин не найден.
        """
        try:
            entry = PluginRegistry.get(plugin_name)
        except Exception:
            _logger.exception("Ошибка при получении плагина '%s' из PluginRegistry", plugin_name)
            return None

        if entry is None:
            return None

        try:
            # Базовые поля
            base = {
                "name": entry.name,
                "category": entry.category,
                "description": entry.description,
                "class_path": entry.class_path,
                "inputs": len(entry.inputs),
                "outputs": len(entry.outputs),
                "enabled": entry.name not in self._disabled_plugins,
                "instances": 0,
                "metrics": self._metrics_cache.get(entry.name),
            }

            # Детализация портов
            input_ports = [
                {
                    "name": p.name,
                    "dtype": p.dtype,
                    "shape": p.shape,
                    "optional": p.optional,
                    "description": p.description,
                }
                for p in entry.inputs
            ]
            output_ports = [
                {
                    "name": p.name,
                    "dtype": p.dtype,
                    "shape": p.shape,
                    "optional": p.optional,
                    "description": p.description,
                }
                for p in entry.outputs
            ]

            return {**base, "input_ports": input_ports, "output_ports": output_ports}

        except Exception:
            _logger.exception("Ошибка при сборке детальных данных плагина '%s'", plugin_name)
            return None

    def filter_plugins(
        self,
        category: str | None = None,
        search: str = "",
    ) -> list[dict]:
        """Фильтровать плагины по категории и/или тексту поиска.

        Args:
            category: категория плагина (None = все категории).
            search: подстрока для поиска в name + description (case-insensitive).

        Returns:
            Отфильтрованный list[dict].
        """
        plugins = self.get_all_plugins()

        # Фильтр по категории
        if category is not None:
            plugins = [p for p in plugins if p["category"] == category]

        # Поиск по имени и описанию
        if search:
            search_lower = search.lower()
            plugins = [
                p for p in plugins
                if search_lower in p["name"].lower()
                or search_lower in p["description"].lower()
            ]

        return plugins

    def set_enabled(self, plugin_name: str, enabled: bool) -> None:
        """Включить или отключить плагин в UI-каталоге.

        Не влияет на запущенные инстансы плагина.

        Args:
            plugin_name: имя плагина.
            enabled: True — включить, False — отключить.
        """
        if enabled:
            self._disabled_plugins.discard(plugin_name)
        else:
            self._disabled_plugins.add(plugin_name)

        self.plugins_updated.emit()

    def reload_plugins(self):
        """Перезагрузить плагины через PluginManager.

        Если PluginManager не задан — только эмитит сигнал обновления.

        Returns:
            PluginDiscoveryResult если PluginManager доступен, иначе None.
        """
        result = None

        if self._plugin_manager is not None:
            try:
                result = self._plugin_manager.reload()
                _logger.info("Перезагрузка плагинов выполнена: %s", result)
            except Exception:
                _logger.exception("Ошибка при перезагрузке плагинов")
        else:
            _logger.debug("PluginManager не задан — reload пропущен")

        self.plugins_updated.emit()
        return result

    def get_default_config(self, plugin_name: str) -> dict:
        """Получить дефолтную конфигурацию плагина.

        Args:
            plugin_name: имя плагина.

        Returns:
            dict конфигурации (пустой если не задана).
        """
        return dict(self._default_configs.get(plugin_name, {}))

    def set_default_config(self, plugin_name: str, config: dict) -> None:
        """Сохранить дефолтную конфигурацию плагина.

        Args:
            plugin_name: имя плагина.
            config: словарь конфигурации.
        """
        self._default_configs[plugin_name] = dict(config)
