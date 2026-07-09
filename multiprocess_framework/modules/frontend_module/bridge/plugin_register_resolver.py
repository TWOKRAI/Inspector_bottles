# -*- coding: utf-8 -*-
"""Резолвер адреса плагина для live field-write (E1/Task 5.4; ранее Task 2.1).

Назначение: по `(process_name, plugin_index)` из editor-топологии вернуть имя регистра
плагина (= ``plugin_name``), которым адресуется live-изменение поля.

Почему ``plugin_name`` = имя регистра:
    Внутри процесса ``PluginOrchestrator._init_registers`` ключует регистры по
    ``plugin.name`` (``schemas[plugin.name] = instance``), а ``plugin.name`` берётся из
    ``plugin_name`` YAML (``_load_plugin``: ``instance.name = plugin_name``). GUI-side
    ``RegistersManager.from_registry`` тоже ключует по имени плагина
    (``registers[entry.name]``). Значит один и тот же ``plugin_name`` адресует регистр
    и в GUI, и в живом процессе — общий ключ для ``set_value`` (GUI) и ``register_update`` (IPC).

Dict at Boundary: работает с dict-топологией (``services.topology.load().to_dict()``).
Чистая функция — ноль Qt/приложение-зависимостей (E1 carve: прототип → framework).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["resolve_plugin_register"]


def resolve_plugin_register(
    topology: dict[str, Any],
    process_name: str,
    plugin_index: int,
) -> str | None:
    """Вернуть имя регистра (``plugin_name``) плагина по индексу в процессе.

    Args:
        topology: dict-топология с ключом ``processes`` (список процессов).
        process_name: имя процесса-владельца.
        plugin_index: индекс плагина в цепочке процесса (нода=плагин, D.1).

    Returns:
        ``plugin_name`` плагина, либо ``None`` если процесс/индекс не найден или
        у плагина пустое имя. Вызывающая сторона при ``None`` делает fallback на
        ``process_name`` (legacy-конвенция 1 плагин = 1 процесс = register_name).

    Pre:
        - ``topology`` — dict (иначе трактуется как без процессов → ``None``);
          процессы/плагины могут быть dict ИЛИ объектами с атрибутами.
    Post:
        - чистая функция: ``topology`` не мутируется, side-effect'ов нет (только debug-лог);
        - ``plugin_index`` вне ``[0, len(plugins))`` → ``None`` (не исключение).
    """
    processes = topology.get("processes", []) if isinstance(topology, dict) else []
    for proc in processes:
        name = proc.get("process_name", "") if isinstance(proc, dict) else getattr(proc, "process_name", "")
        if name != process_name:
            continue
        plugins = proc.get("plugins", []) if isinstance(proc, dict) else getattr(proc, "plugins", [])
        if not (0 <= plugin_index < len(plugins)):
            logger.debug(
                "resolve_plugin_register: индекс %d вне диапазона для процесса '%s' (плагинов: %d)",
                plugin_index,
                process_name,
                len(plugins),
            )
            return None
        pl = plugins[plugin_index]
        plugin_name = pl.get("plugin_name", "") if isinstance(pl, dict) else getattr(pl, "plugin_name", "")
        return plugin_name or None
    logger.debug("resolve_plugin_register: процесс '%s' не найден в топологии", process_name)
    return None
