"""Прототип-specific утилиты для RegistersManager.

RegistersManager (с from_registry, get_fields, get_categories) живёт в framework.
Здесь — только prototype-specific функция build_rm_from_topology(),
которая знает формат topology YAML dict.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from multiprocess_framework.modules.registers_module import RegistersManager


class _RawRegisterData(BaseModel):
    """Внутренний wrapper-регистр для хранения данных из YAML-файла базового слоя.

    Используется только внутри build_rm_from_topology() для регистров,
    загруженных из base_registers_dir, но не имеющих соответствующего
    plugin_registry entry. Topology-регистры (реальные BaseModel) перекрывают их.

    Атрибуты:
        data: сырые данные из YAML в виде dict.
    """

    data: dict[str, Any] = {}


def build_rm_from_topology(
    topology: dict[str, Any],
    plugin_registry: Any | None = None,
    *,
    base_registers_dir: Path | None = None,
    **kwargs: Any,
) -> RegistersManager:
    """Построить RegistersManager из topology dict (prototype-specific формат).

    Двухслойный подход: базовый слой из YAML-файлов (если передан base_registers_dir),
    поверх которого active-слой из topology. При пересечении имён — topology wins.

    Args:
        topology: dict с ключом "processes" -> list of process dicts.
        plugin_registry: PluginRegistry для lookup register_classes.
        base_registers_dir: опциональный Path до директории с базовыми регистрами.
            Каждый *.yaml файл читается и добавляется как регистр (stem = имя).
            При ошибке парсинга — файл пропускается без исключения.
            Если None или директория не существует — базовый слой пропускается.
        **kwargs: Дополнительные аргументы для RegistersManager.__init__.

    Returns:
        Готовый RegistersManager с регистрами из базового слоя + topology.
        При пересечении имён topology всегда перекрывает базовый слой.
    """
    registers: dict[str, Any] = {}
    categories: dict[str, str] = {}

    # --- Базовый слой: YAML-файлы из base_registers_dir ---
    if base_registers_dir is not None and base_registers_dir.exists():
        for yaml_path in sorted(base_registers_dir.glob("*.yaml")):
            register_name = yaml_path.stem
            try:
                raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    # Файл содержит не dict (список или скаляр) — пропустить
                    continue
                registers[register_name] = _RawRegisterData(data=raw)
            except Exception:  # nosec B110 — невалидный YAML/ошибка чтения: graceful skip
                # Файл пропускается — менеджер создаётся без него
                pass

    # --- Active-слой: регистры из topology (topology wins при пересечении) ---
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
                    # Topology всегда перекрывает базовый слой (включая _RawRegisterData)
                    registers[plugin_name] = instance
                    categories[plugin_name] = entry.category

    return RegistersManager(registers=registers, plugin_categories=categories, **kwargs)
