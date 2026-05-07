"""RegistersManager v2 — фабрика поверх FW RegistersManager.

Добавляет:
- from_registry(): автоматическое построение из PluginRegistry
- get_fields(): FieldInfo для GUI-генерации
- from_topology(): построение из topology YAML dict

Внутри — делегирует в FW RegistersManager (pub/sub, validation, dispatch).
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.registers_module import RegistersManager

from .field_info import FieldInfo, extract_fields


class RegistersManagerV2(RegistersManager):
    """RegistersManager с auto-build из PluginRegistry и FieldInfo.

    Расширяет FW RegistersManager:
    - from_registry() — автобилд из register_bindings всех плагинов
    - from_topology() — автобилд из topology dict (process → plugins)
    - get_fields() — FieldInfo для GUI
    - plugin_categories — mapping plugin_name → category
    """

    def __init__(
        self,
        registers: dict[str, Any] | None = None,
        plugin_categories: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(registers=registers, **kwargs)
        self._plugin_categories: dict[str, str] = plugin_categories or {}
        # Кэш FieldInfo по plugin_name
        self._fields_cache: dict[str, list[FieldInfo]] = {}

    @classmethod
    def from_registry(cls, registry: Any, **kwargs: Any) -> RegistersManagerV2:
        """Построить из PluginRegistry — сканирует register_bindings всех плагинов.

        Args:
            registry: PluginRegistry (или любой объект с .list() → [PluginEntry]).
        """
        registers: dict[str, Any] = {}
        categories: dict[str, str] = {}

        for entry in registry.list():
            reg_classes = getattr(entry, "register_classes", None) or []
            if reg_classes:
                # Инстанцируем первый register-класс (convention: 1 register per plugin)
                instance = reg_classes[0]()
                registers[entry.name] = instance
                categories[entry.name] = entry.category

        return cls(registers=registers, plugin_categories=categories, **kwargs)

    @classmethod
    def from_topology(
        cls,
        topology: dict[str, Any],
        plugin_registry: Any | None = None,
        **kwargs: Any,
    ) -> RegistersManagerV2:
        """Построить из topology dict — знает какие плагины с каким конфигом.

        Args:
            topology: dict с ключом "processes" → list of process dicts.
            plugin_registry: PluginRegistry для lookup register_bindings.
        """
        registers: dict[str, Any] = {}
        categories: dict[str, str] = {}

        processes = topology.get("processes", [])
        for proc in processes:
            plugins = proc.get("plugins", [])
            for plugin_dict in plugins:
                plugin_name = plugin_dict.get("plugin_name", "")
                if not plugin_name:
                    continue

                # Из registry — register_bindings
                if plugin_registry is not None:
                    entry = plugin_registry.get(plugin_name)
                    if entry and getattr(entry, "register_classes", None):
                        reg_cls = entry.register_classes[0]
                        # Инстанцировать с YAML overrides
                        reg_fields = {
                            k: v for k, v in plugin_dict.items()
                            if k in reg_cls.model_fields
                        }
                        instance = reg_cls(**reg_fields)
                        registers[plugin_name] = instance
                        categories[plugin_name] = entry.category

        return cls(registers=registers, plugin_categories=categories, **kwargs)

    def get_fields(self, plugin_name: str) -> list[FieldInfo]:
        """Список FieldInfo для GUI-генерации виджетов.

        Args:
            plugin_name: Имя плагина (= имя регистра).

        Returns:
            Список FieldInfo с метаданными полей.
        """
        if plugin_name in self._fields_cache:
            return self._fields_cache[plugin_name]

        reg = self.get_register(plugin_name)
        if reg is None:
            return []

        category = self._plugin_categories.get(plugin_name, "")
        fields = extract_fields(plugin_name, type(reg), category=category)
        self._fields_cache[plugin_name] = fields
        return fields

    def get_categories(self) -> dict[str, list[str]]:
        """Группировка плагинов по категориям.

        Returns:
            {category: [plugin_name, ...]}
        """
        result: dict[str, list[str]] = {}
        for name in self.register_names():
            cat = self._plugin_categories.get(name, "other")
            result.setdefault(cat, []).append(name)
        return result

    def set_value(
        self,
        plugin_name: str,
        field_name: str,
        value: Any,
    ) -> bool:
        """Установить значение (алиас для set_field_value, возвращает bool)."""
        ok, _err = self.set_field_value(plugin_name, field_name, value)
        return ok

    def validate(
        self,
        plugin_name: str,
        field_name: str,
        value: Any,
    ) -> tuple[bool, str | None]:
        """Валидировать значение (алиас для validate_field_value)."""
        return self.validate_field_value(plugin_name, field_name, value)
