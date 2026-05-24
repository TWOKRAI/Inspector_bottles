"""PluginManager — автоматическая загрузка и hot-reload плагинов.

Наследует BaseManager + ObservableMixin для интеграции с системой
логирования, метрик и ошибок через инжектируемые менеджеры.

Сканирует список директорий на наличие plugin.py файлов,
импортирует их (что триггерит @register_plugin -> PluginRegistry),
поддерживает hot-reload без перезапуска.

Использование::

    manager = PluginManager(
        registry=PluginRegistry,
        paths=[Path("plugins/"), Path("extra_plugins/")],
        logger=logger_manager,
    )
    manager.initialize()
    result = manager.discover()    # первичная загрузка
    result = manager.reload()      # hot-reload
    result = manager.rescan()      # алиас reload() (для GUI)
    manager.list_discovered()      # список загруженных плагинов
"""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path
from typing import Any

from ...base_manager import BaseManager, ObservableMixin


class PluginDiscoveryResult:
    """Результат сканирования директорий плагинов.

    Attributes:
        loaded:      Список успешно загруженных module path.
        failed:      Список кортежей (module_path, текст_ошибки) для неудачных импортов.
        new_plugins: Имена плагинов, появившихся в PluginRegistry после сканирования.
    """

    def __init__(self) -> None:
        self.loaded: list[str] = []
        self.failed: list[tuple[str, str]] = []
        self.new_plugins: list[str] = []

    @property
    def total(self) -> int:
        """Общее количество обработанных модулей (загруженные + ошибки)."""
        return len(self.loaded) + len(self.failed)

    @property
    def errors(self) -> list[tuple[str, str]]:
        """Алиас для failed — удобный доступ к ошибкам."""
        return self.failed

    def __repr__(self) -> str:
        return (
            f"<PluginDiscoveryResult loaded={len(self.loaded)} failed={len(self.failed)} new={len(self.new_plugins)}>"
        )


class PluginManager(BaseManager, ObservableMixin):
    """Менеджер плагинов — auto-discovery + hot-reload.

    Принцип работы:
    1. Рекурсивно сканирует указанные директории на наличие plugin.py
    2. Импортирует каждый найденный модуль
    3. @register_plugin декоратор автоматически добавляет в PluginRegistry
    4. При reload() / rescan() — переимпортирует модули (importlib.reload)

    Совместим с PluginRegistry из фреймворка — не дублирует, а дополняет.

    Args:
        registry: Экземпляр PluginRegistry (глобальный каталог плагинов).
        paths:    Список путей к директориям с плагинами.
        logger:   LoggerManager или None (ObservableMixin fallback — тихо).
        stats:    StatsManager или None.
        error:    ErrorManager или None.
    """

    def __init__(
        self,
        registry: Any,
        paths: list[Path | str],
        logger: Any = None,
        stats: Any = None,
        error: Any = None,
    ) -> None:
        BaseManager.__init__(self, manager_name="plugin_manager")
        ObservableMixin.__init__(
            self,
            managers={"logger": logger, "stats": stats, "error": error},
        )

        self._plugin_registry = registry
        self._plugin_paths: list[Path] = [Path(p).resolve() for p in paths]
        self._loaded_modules: dict[str, Any] = {}  # module_path -> module object
        self._discovered = False
        self._discover_count = 0
        self._last_discover_time: float | None = None

    # =========================================================================
    # СВОЙСТВА
    # =========================================================================

    @property
    def plugin_paths(self) -> list[Path]:
        """Список директорий для сканирования плагинов."""
        return list(self._plugin_paths)

    @property
    def is_discovered(self) -> bool:
        """Был ли выполнен хотя бы один discover."""
        return self._discovered

    # =========================================================================
    # ЖИЗНЕННЫЙ ЦИКЛ (BaseManager)
    # =========================================================================

    def initialize(self) -> bool:
        """Инициализация менеджера.

        Выполняет первичное сканирование если ещё не выполнялось.

        Returns:
            True если инициализация успешна.
        """
        if self.is_initialized:
            return True

        self.is_initialized = True
        self._log_info(f"PluginManager инициализирован, пути: {self._plugin_paths}")
        return True

    def shutdown(self) -> bool:
        """Корректное завершение работы менеджера.

        Returns:
            True если завершение успешно.
        """
        self._loaded_modules.clear()
        self._discovered = False
        self.is_initialized = False
        self._log_info("PluginManager завершён")
        return True

    # =========================================================================
    # ПУБЛИЧНЫЙ API — DISCOVERY
    # =========================================================================

    def discover(self) -> PluginDiscoveryResult:
        """Первичное сканирование: найти и импортировать все plugin.py.

        Вызывается один раз при старте приложения.
        Повторные вызовы пропускают уже загруженные модули.

        Returns:
            PluginDiscoveryResult — статистика загрузки.
        """
        start = time.monotonic()
        result = PluginDiscoveryResult()
        known_before = set(self._plugin_registry.names())

        for plugins_dir in self._plugin_paths:
            for plugin_file in self._find_plugin_files_in(plugins_dir):
                module_path = self._file_to_module_path(plugin_file, plugins_dir)
                if not module_path:
                    continue

                if module_path in self._loaded_modules:
                    continue  # уже загружен

                self._import_module(module_path, result)

        # Определяем какие плагины появились в реестре
        known_after = set(self._plugin_registry.names())
        result.new_plugins = sorted(known_after - known_before)

        self._discovered = True
        self._discover_count += 1
        self._last_discover_time = time.monotonic() - start

        self._log_info(
            f"Plugin discover: {len(result.loaded)} загружено, "
            f"{len(result.failed)} ошибок, "
            f"{len(result.new_plugins)} новых в реестре"
        )
        return result

    def reload(self) -> PluginDiscoveryResult:
        """Hot-reload: обнаружить новые плагины + перезагрузить изменённые.

        1. Сканирует все директории на новые plugin.py
        2. Новые — импортирует
        3. Существующие — importlib.reload (обновляет код без перезапуска)

        Returns:
            PluginDiscoveryResult — статистика.
        """
        start = time.monotonic()
        result = PluginDiscoveryResult()
        known_before = set(self._plugin_registry.names())

        for plugins_dir in self._plugin_paths:
            for plugin_file in self._find_plugin_files_in(plugins_dir):
                module_path = self._file_to_module_path(plugin_file, plugins_dir)
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
                    self._log_debug(f"Плагин (пере)загружен: {module_path}")
                except Exception as e:
                    result.failed.append((module_path, str(e)))
                    self._log_warning(f"Ошибка reload плагина: {module_path} — {e}")

        known_after = set(self._plugin_registry.names())
        result.new_plugins = sorted(known_after - known_before)
        self._last_discover_time = time.monotonic() - start

        self._log_info(
            f"Plugin reload: {len(result.loaded)} обработано, "
            f"{len(result.failed)} ошибок, "
            f"{len(result.new_plugins)} новых в реестре"
        )
        return result

    def rescan(self) -> PluginDiscoveryResult:
        """Алиас для reload() — публичный контракт для GUI (Phase 2).

        Returns:
            PluginDiscoveryResult — статистика.
        """
        return self.reload()

    def list_discovered(self) -> list[dict[str, Any]]:
        """Список загруженных плагинов (для UI).

        Returns:
            Список dict'ов с информацией о каждом плагине:
            name, category, description, class_path, inputs, outputs.
        """
        plugins: list[dict[str, Any]] = []
        for entry in self._plugin_registry.list():
            plugins.append(
                {
                    "name": entry.name,
                    "category": entry.category,
                    "description": entry.description,
                    "class_path": entry.class_path,
                    "inputs": len(entry.inputs),
                    "outputs": len(entry.outputs),
                }
            )
        return plugins

    # =========================================================================
    # ПУБЛИЧНЫЙ API — ДИАГНОСТИКА (BaseManager)
    # =========================================================================

    def get_stats(self) -> dict[str, Any]:
        """Статистика менеджера плагинов.

        Returns:
            dict с ключами: manager_name, is_initialized, is_discovered,
            plugin_paths, loaded_modules_count, registry_size,
            discover_count, last_discover_time_ms.
        """
        base = super().get_stats()
        base.update(
            {
                "is_discovered": self._discovered,
                "plugin_paths": [str(p) for p in self._plugin_paths],
                "loaded_modules_count": len(self._loaded_modules),
                "registry_size": len(self._plugin_registry),
                "discover_count": self._discover_count,
                "last_discover_time_ms": (
                    round(self._last_discover_time * 1000, 2) if self._last_discover_time is not None else None
                ),
            }
        )
        return base

    def get_debug_info(self) -> dict[str, Any]:
        """Подробная информация для отладки.

        Returns:
            dict с расширенной информацией: загруженные модули,
            содержимое реестра, пути сканирования.
        """
        base = super().get_debug_info()
        base.update(
            {
                "loaded_modules": list(self._loaded_modules.keys()),
                "plugin_paths": [str(p) for p in self._plugin_paths],
                "registry_plugins": self._plugin_registry.names(),
                "is_discovered": self._discovered,
            }
        )
        return base

    # =========================================================================
    # ВНУТРЕННИЕ МЕТОДЫ
    # =========================================================================

    def _find_plugin_files_in(self, plugins_dir: Path) -> list[Path]:
        """Найти все plugin.py файлы рекурсивно в указанной директории.

        Args:
            plugins_dir: Корневая директория для сканирования.

        Returns:
            Отсортированный список путей к plugin.py файлам.
        """
        if not plugins_dir.exists():
            self._log_warning(f"Директория плагинов не найдена: {plugins_dir}")
            return []
        return sorted(plugins_dir.rglob("plugin.py"))

    @staticmethod
    def _file_to_module_path(plugin_file: Path, plugins_root: Path) -> str | None:
        """Конвертировать путь файла в dotted module path.

        Использует sys.path для определения корня пакета —
        не привязан к конкретному имени директории.

        Args:
            plugin_file:  Абсолютный путь к plugin.py файлу.
            plugins_root: Корневая директория плагинов (для контекста).

        Returns:
            Dotted module path или None если не удалось вычислить.

        Пример::

            plugins/cameras/camera_service/plugin.py
            -> multiprocess_prototype.plugins.cameras.camera_service.plugin
        """
        resolved = plugin_file.resolve()

        # Ищем ближайший sys.path entry как корень пакета
        for sp in sys.path:
            if not sp:
                continue
            try:
                sp_resolved = Path(sp).resolve()
                rel = resolved.relative_to(sp_resolved)
                parts = rel.with_suffix("").parts
                module_path = ".".join(parts)
                return module_path
            except (ValueError, OSError):
                continue

        return None

    def _import_module(self, module_path: str, result: PluginDiscoveryResult) -> None:
        """Импортировать один модуль и записать результат.

        Args:
            module_path: Dotted module path для импорта.
            result:      PluginDiscoveryResult для записи результата.
        """
        try:
            module = importlib.import_module(module_path)
            self._loaded_modules[module_path] = module
            result.loaded.append(module_path)
            self._log_debug(f"Плагин загружен: {module_path}")
        except Exception as e:
            result.failed.append((module_path, str(e)))
            self._log_warning(f"Ошибка загрузки плагина: {module_path} — {e}")
