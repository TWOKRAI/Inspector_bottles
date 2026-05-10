"""PluginManager — автоматическая загрузка и hot-reload плагинов.

Сканирует директорию plugins/, импортирует все plugin.py модули,
что триггерит @register_plugin → PluginRegistry.

Использование:
    manager = PluginManager("multiprocess_prototype/plugins")
    manager.discover()           # первичная загрузка
    manager.reload()             # hot-reload (новые плагины без перезапуска)
    manager.list_discovered()    # список загруженных плагинов

Интеграция с GUI:
    Кнопка «Обновить плагины» → manager.reload() → обновить UI-каталог.
"""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from typing import Any

from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry

_logger = logging.getLogger(__name__)


class PluginDiscoveryResult:
    """Результат сканирования директории плагинов."""

    def __init__(self) -> None:
        self.loaded: list[str] = []      # успешно загруженные модули
        self.failed: list[tuple[str, str]] = []  # (путь, ошибка)
        self.new_plugins: list[str] = [] # новые плагины в PluginRegistry

    @property
    def total(self) -> int:
        return len(self.loaded) + len(self.failed)

    def __repr__(self) -> str:
        return (
            f"<DiscoveryResult loaded={len(self.loaded)} "
            f"failed={len(self.failed)} new={len(self.new_plugins)}>"
        )


class PluginManager:
    """Менеджер плагинов — auto-discovery + hot-reload.

    Принцип работы:
    1. Рекурсивно сканирует plugins_dir на наличие plugin.py файлов
    2. Импортирует каждый найденный модуль
    3. @register_plugin декоратор автоматически добавляет в PluginRegistry
    4. При reload() — переимпортирует модули (importlib.reload)

    Совместим с PluginRegistry из фреймворка — не дублирует, а дополняет.
    """

    def __init__(self, plugins_dir: str | Path) -> None:
        self._plugins_dir = Path(plugins_dir).resolve()
        self._loaded_modules: dict[str, Any] = {}  # module_path → module object
        self._discovered = False

    @property
    def plugins_dir(self) -> Path:
        return self._plugins_dir

    @property
    def is_discovered(self) -> bool:
        return self._discovered

    def discover(self) -> PluginDiscoveryResult:
        """Первичное сканирование: найти и импортировать все plugin.py.

        Вызывается один раз при старте приложения.
        Повторные вызовы пропускают уже загруженные модули.

        Returns:
            PluginDiscoveryResult — статистика загрузки.
        """
        result = PluginDiscoveryResult()
        known_before = set(PluginRegistry.names())

        for plugin_file in self._find_plugin_files():
            module_path = self._file_to_module_path(plugin_file)
            if not module_path:
                continue

            if module_path in self._loaded_modules:
                continue  # уже загружен

            try:
                module = importlib.import_module(module_path)
                self._loaded_modules[module_path] = module
                result.loaded.append(module_path)
                _logger.debug("Plugin loaded: %s", module_path)
            except Exception as e:
                result.failed.append((module_path, str(e)))
                _logger.warning("Plugin load failed: %s — %s", module_path, e)

        # Определяем какие плагины появились
        known_after = set(PluginRegistry.names())
        result.new_plugins = list(known_after - known_before)

        self._discovered = True
        _logger.info(
            "Plugin discovery: %d loaded, %d failed, %d new in registry",
            len(result.loaded), len(result.failed), len(result.new_plugins)
        )
        return result

    def reload(self) -> PluginDiscoveryResult:
        """Hot-reload: обнаружить новые плагины + перезагрузить изменённые.

        1. Сканирует директорию на новые plugin.py
        2. Новые — импортирует
        3. Существующие — importlib.reload (обновляет код без перезапуска)

        Returns:
            PluginDiscoveryResult — статистика.
        """
        result = PluginDiscoveryResult()
        known_before = set(PluginRegistry.names())

        for plugin_file in self._find_plugin_files():
            module_path = self._file_to_module_path(plugin_file)
            if not module_path:
                continue

            try:
                if module_path in self._loaded_modules:
                    # Перезагрузка существующего модуля
                    module = importlib.reload(self._loaded_modules[module_path])
                    self._loaded_modules[module_path] = module
                    result.loaded.append(f"{module_path} (reloaded)")
                else:
                    # Новый модуль
                    module = importlib.import_module(module_path)
                    self._loaded_modules[module_path] = module
                    result.loaded.append(f"{module_path} (new)")
                _logger.debug("Plugin (re)loaded: %s", module_path)
            except Exception as e:
                result.failed.append((module_path, str(e)))
                _logger.warning("Plugin reload failed: %s — %s", module_path, e)

        known_after = set(PluginRegistry.names())
        result.new_plugins = list(known_after - known_before)

        _logger.info(
            "Plugin reload: %d processed, %d failed, %d new in registry",
            len(result.loaded), len(result.failed), len(result.new_plugins)
        )
        return result

    def list_discovered(self) -> list[dict[str, str]]:
        """Список загруженных плагинов (для UI).

        Returns:
            Список dict'ов: name, category, description, class_path, module_path.
        """
        plugins = []
        for entry in PluginRegistry.list():
            plugins.append({
                "name": entry.name,
                "category": entry.category,
                "description": entry.description,
                "class_path": entry.class_path,
                "inputs": len(entry.inputs),
                "outputs": len(entry.outputs),
            })
        return plugins

    # --- Внутренние методы ---

    def _find_plugin_files(self) -> list[Path]:
        """Найти все plugin.py файлы рекурсивно."""
        if not self._plugins_dir.exists():
            _logger.warning("Plugins directory not found: %s", self._plugins_dir)
            return []
        return sorted(self._plugins_dir.rglob("plugin.py"))

    def _file_to_module_path(self, plugin_file: Path) -> str | None:
        """Конвертировать путь файла в dotted module path.

        plugins/cameras/camera_service/plugin.py
        → multiprocess_prototype.plugins.cameras.camera_service.plugin
        """
        try:
            # Ищем корень пакета (multiprocess_prototype) в родительских директориях
            rel = plugin_file.relative_to(self._plugins_dir.parent)
            parts = rel.with_suffix("").parts
            # Определяем корневой пакет
            package_root = self._plugins_dir.parent.name
            module_path = f"{package_root}.{'.'.join(parts)}"
            return module_path
        except ValueError:
            return None

    def _ensure_sys_path(self) -> None:
        """Убедиться что корневая директория в sys.path."""
        root = str(self._plugins_dir.parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
