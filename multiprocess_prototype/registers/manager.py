"""Прототип-specific утилиты для RegistersManager.

RegistersManager (с from_registry, get_fields, get_categories) живёт в framework.
Здесь — только prototype-specific функция build_rm_from_topology(),
которая знает формат topology YAML dict.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.registers_module import RegistersManager


def build_rm_from_topology(
    topology: dict[str, Any],
    plugin_registry: Any | None = None,
    **kwargs: Any,
) -> RegistersManager:
    """Построить RegistersManager из topology dict (prototype-specific формат).

    Args:
        topology: dict с ключом "processes" -> list of process dicts.
        plugin_registry: PluginRegistry для lookup register_classes.
        **kwargs: Дополнительные аргументы для RegistersManager.__init__.

    Returns:
        Готовый RegistersManager с регистрами из topology.
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

            # Из registry — register_classes
            if plugin_registry is not None:
                entry = plugin_registry.get(plugin_name)
                if entry and getattr(entry, "register_classes", None):
                    reg_cls = entry.register_classes[0]
                    # Инстанцировать с YAML overrides
                    reg_fields = {k: v for k, v in plugin_dict.items() if k in reg_cls.model_fields}
                    instance = reg_cls(**reg_fields)
                    registers[plugin_name] = instance
                    categories[plugin_name] = entry.category

    return RegistersManager(registers=registers, plugin_categories=categories, **kwargs)
