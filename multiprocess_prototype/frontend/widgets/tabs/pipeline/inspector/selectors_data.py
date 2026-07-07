# -*- coding: utf-8 -*-
"""Чистая логика селекторов инспектора — БЕЗ Qt (F.6, разрез god-файла).

Функции читают данные из services-протоколов (recipes / displays / topology) и
возвращают простые Python-структуры для наполнения combo. Отсутствие Qt делает их
юнит-тестируемыми на fake-store без QApplication.

Вынесено из NodeInspectorPanel (кластер C дизайна): панель делегирует сюда, оставаясь
тонким фасадом-оркестратором.
"""

from __future__ import annotations

import logging
from collections import namedtuple
from typing import Any

logger = logging.getLogger(__name__)

# Thin wrapper: combo-код инспектора ожидает .id и .name, а domain DisplaySpec имеет
# display_id / display_name. DisplayEntry — адаптер значений для отображения.
DisplayEntry = namedtuple("DisplayEntry", ["id", "name"])


def worker_label(plugin_category: str, plugin_name: str, step: int, total: int) -> str:
    """Метка воркера плагина — соответствует авто-назначению в GenericProcess.

    source → свой поток source_producer_<name> (параллельно);
    processing → общий pipeline_executor (последовательно, шаг N/total).
    """
    if plugin_category == "source":
        return f"source_producer_{plugin_name} · свой поток (параллельно)"
    if total > 1:
        return f"pipeline_executor · последовательно (шаг {step}/{total})"
    return "pipeline_executor · последовательно"


def process_names_from_recipe(recipes: Any) -> list[str]:
    """Имена процессов из активного рецепта (RecipeStore Protocol).

    Возвращает пустой список, если store недоступен, активного рецепта нет,
    рецепт/blueprint не dict, или процессы заданы объектами без process_name.

    Args:
        recipes: services.recipes (get_active / read_raw) или None.
    """
    if recipes is None:
        return []
    try:
        active_slug = recipes.get_active()
        if not active_slug:
            return []

        recipe_dict = recipes.read_raw(active_slug)
        if not isinstance(recipe_dict, dict):
            return []

        blueprint = recipe_dict.get("blueprint", {})
        if not isinstance(blueprint, dict):
            return []

        processes = blueprint.get("processes", [])
        names: list[str] = []
        for proc in processes:
            if isinstance(proc, dict):
                name = proc.get("process_name", "")
            else:
                name = getattr(proc, "process_name", "")
            if name:
                names.append(name)
        return names
    except Exception:
        logger.debug("Не удалось получить список процессов из рецепта", exc_info=True)
        return []


def display_entries(displays: Any) -> list[DisplayEntry]:
    """Список DisplayEntry из DisplayCatalog (services.displays).

    DisplaySpec имеет display_id / display_name; combo использует .id / .name —
    оборачиваем в DisplayEntry. Пустой список при недоступном каталоге.

    Args:
        displays: services.displays (list_displays) или None.
    """
    if displays is None:
        return []
    try:
        specs = displays.list_displays()
        return [DisplayEntry(id=spec.display_id, name=spec.display_name) for spec in specs]
    except Exception:
        logger.debug("Не удалось получить список дисплеев из реестра", exc_info=True)
        return []


def workers_for_process(topology: Any, process_name: str) -> list[str]:
    """Имена воркеров процесса из топологии (+ синтетический message_processor).

    Единый источник с вкладкой «Процессы»: services.topology → Process.workers.
    Пусто/нет процесса/нет топологии → только message_processor.

    Args:
        topology: services.topology (load → find_process) или None.
        process_name: имя процесса.
    """
    if topology is None or not process_name:
        return ["message_processor"]
    try:
        topo = topology.load()
        proc = topo.find_process(process_name)
        workers = [w.worker_name for w in proc.workers] if proc is not None else []
    except Exception:
        logger.debug("Не удалось получить воркеры процесса '%s'", process_name, exc_info=True)
        workers = []
    if "message_processor" not in workers:
        workers.insert(0, "message_processor")
    return workers
