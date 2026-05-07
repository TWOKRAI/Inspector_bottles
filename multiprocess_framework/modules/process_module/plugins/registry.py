"""PluginRegistry — глобальный каталог плагинов.

Регистрация через декоратор:
    @register_plugin("color_mask", category="processing")
    class ColorMaskPlugin(ProcessModulePlugin):
        ...

Доступ к каталогу:
    PluginRegistry.list()                           # все плагины
    PluginRegistry.get("color_mask")                # по имени
    PluginRegistry.filter(category="processing")    # по категории
    PluginRegistry.compatible_with(port)            # совместимые с портом

Аналог: GStreamer element factory + Node-RED registerType.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .base import ProcessModulePlugin
    from .port import Port


class PluginEntry:
    """Запись о плагине в каталоге."""

    def __init__(
        self,
        name: str,
        plugin_class: type[ProcessModulePlugin],
        category: str = "",
        description: str = "",
    ) -> None:
        self.name = name
        self.plugin_class = plugin_class
        self.category = category
        self.description = description

        # V3_MY_PURE: register-классы из plugin.register_schema()
        try:
            self.register_classes: list = plugin_class.register_schema()
        except Exception:
            self.register_classes = []

    @property
    def inputs(self) -> list[Port]:
        """Входные порты плагина."""
        return list(getattr(self.plugin_class, "inputs", []))

    @property
    def outputs(self) -> list[Port]:
        """Выходные порты плагина."""
        return list(getattr(self.plugin_class, "outputs", []))

    @property
    def class_path(self) -> str:
        """Полный dotted path к классу."""
        cls = self.plugin_class
        return f"{cls.__module__}.{cls.__qualname__}"

    def __repr__(self) -> str:
        ins = len(self.inputs)
        outs = len(self.outputs)
        return f"<Plugin '{self.name}' [{self.category}] {ins}in/{outs}out>"


class _PluginRegistry:
    """Глобальный каталог плагинов (singleton через модуль)."""

    def __init__(self) -> None:
        self._plugins: dict[str, PluginEntry] = {}

    def register(
        self,
        name: str,
        plugin_class: type[ProcessModulePlugin],
        category: str = "",
        description: str = "",
    ) -> None:
        """Зарегистрировать плагин в каталоге."""
        if name in self._plugins:
            existing = self._plugins[name]
            # Перезапись того же класса — OK (reload)
            if existing.plugin_class is not plugin_class:
                raise ValueError(
                    f"Плагин '{name}' уже зарегистрирован: "
                    f"{existing.class_path}. "
                    f"Попытка перезаписать: {plugin_class.__module__}.{plugin_class.__qualname__}"
                )

        self._plugins[name] = PluginEntry(
            name=name,
            plugin_class=plugin_class,
            category=category,
            description=description,
        )

    def get(self, name: str) -> PluginEntry | None:
        """Получить плагин по имени."""
        return self._plugins.get(name)

    def list(self) -> list[PluginEntry]:
        """Все зарегистрированные плагины."""
        return list(self._plugins.values())

    def filter(self, category: str) -> list[PluginEntry]:
        """Плагины по категории (source / processing / output)."""
        return [p for p in self._plugins.values() if p.category == category]

    def compatible_with(self, port: Port) -> list[PluginEntry]:
        """Плагины, чей вход совместим с данным портом.

        Используется в UI для фильтрации каталога:
        "что можно подключить после этого плагина?"
        """
        from .port import are_ports_compatible

        result = []
        for entry in self._plugins.values():
            for inp in entry.inputs:
                if are_ports_compatible(port, inp):
                    result.append(entry)
                    break
        return result

    def names(self) -> list[str]:
        """Имена всех зарегистрированных плагинов."""
        return list(self._plugins.keys())

    def discover(self, *plugin_dirs: str) -> int:
        """Автоматическое сканирование директорий с плагинами.

        Ищет файлы plugin.py рекурсивно, импортирует их модули.
        @register_plugin декоратор срабатывает при import — плагины
        автоматически попадают в каталог.

        Args:
            *plugin_dirs: Пути к директориям с плагинами.
                Каждая директория сканируется рекурсивно.

        Returns:
            Количество новых зарегистрированных плагинов.
        """
        import importlib
        import logging
        from pathlib import Path

        logger = logging.getLogger(__name__)
        count_before = len(self._plugins)

        for dir_path in plugin_dirs:
            plugins_root = Path(dir_path).resolve()
            if not plugins_root.is_dir():
                logger.warning("PluginRegistry.discover: директория не найдена: %s", dir_path)
                continue

            # Найти все plugin.py рекурсивно
            for plugin_file in plugins_root.rglob("plugin.py"):
                # Конвертировать путь файла в dotted module path
                module_path = self._file_to_module(plugin_file)
                if module_path is None:
                    continue

                try:
                    importlib.import_module(module_path)
                except Exception as exc:
                    logger.debug(
                        "PluginRegistry.discover: %s — %s: %s",
                        module_path, type(exc).__name__, exc,
                    )

        discovered = len(self._plugins) - count_before
        if discovered > 0:
            logger.info(
                "PluginRegistry.discover: найдено %d новых плагинов (всего %d)",
                discovered, len(self._plugins),
            )
        return discovered

    @staticmethod
    def _file_to_module(file_path) -> str | None:
        """Конвертировать путь к plugin.py в dotted module path.

        Ищет ближайший sys.path entry как корень пакета.
        Поддерживает как абсолютные, так и относительные пути в sys.path.
        """
        import sys
        from pathlib import Path

        path = Path(file_path).resolve()

        # Перебрать sys.path — найти entry, от которого можно вычислить relative path
        for sp in sys.path:
            if not sp:
                continue
            try:
                sp_resolved = Path(sp).resolve()
                rel = path.relative_to(sp_resolved)
                module_path = ".".join(rel.with_suffix("").parts)
                return module_path
            except (ValueError, OSError):
                continue

        return None

    def clear(self) -> None:
        """Очистить каталог (для тестов)."""
        self._plugins.clear()

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, name: str) -> bool:
        return name in self._plugins


# Глобальный экземпляр каталога
PluginRegistry = _PluginRegistry()


def register_plugin(
    name: str,
    category: str = "",
    description: str = "",
):
    """Декоратор для регистрации плагина в глобальном каталоге.

    Использование:
        @register_plugin("color_mask", category="processing")
        class ColorMaskPlugin(ProcessModulePlugin):
            inputs = [Port("frame", dtype="image/bgr", shape="(H, W, 3)")]
            outputs = [Port("mask", dtype="image/gray", shape="(H, W, 1)")]
            ...

    Аналог: Node-RED RED.nodes.registerType + GStreamer GST_ELEMENT_REGISTER_DEFINE.
    """
    def decorator(cls):
        PluginRegistry.register(
            name=name,
            plugin_class=cls,
            category=category,
            description=description,
        )
        # Установить атрибуты если не заданы в классе
        if not getattr(cls, "name", ""):
            cls.name = name
        if not getattr(cls, "category", ""):
            cls.category = category
        return cls

    return decorator
