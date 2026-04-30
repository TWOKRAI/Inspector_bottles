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
