"""blueprint_io.py — конвертеры topology ↔ SystemBlueprint + JSON I/O.

Предоставляет функции для сохранения и загрузки рецептов (SystemBlueprint)
из JSON-файлов, а также конвертацию между форматом ProcessesSectionView
(dict[str, dict]) и форматом SystemBlueprint.

Правило Dict at Boundary соблюдается: между процессами ходят только dict.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from multiprocess_framework.modules.process_module.generic.blueprint import (
    ProcessConfig,
    SystemBlueprint,
    Wire,
)

logger = logging.getLogger(__name__)


def topology_to_blueprint(
    proc_data: dict[str, dict],
    name: str = "untitled",
    description: str = "",
) -> SystemBlueprint:
    """Конвертировать processes dict из topology в SystemBlueprint.

    Args:
        proc_data:   Словарь процессов из ProcessesSectionView.processes.
                     Формат каждого значения:
                     {name, class_path, priority, auto_start, sort_order, plugins}.
        name:        Название рецепта (blueprint.name).
        description: Описание рецепта (blueprint.description).

    Returns:
        SystemBlueprint с processes из proc_data. Wires пустые
        (auto-wiring внутри процессов не требует явных wires).
    """
    process_configs: list[ProcessConfig] = []

    # Сортируем по sort_order для детерминированного порядка
    sorted_items = sorted(
        proc_data.items(),
        key=lambda kv: kv[1].get("sort_order", 0),
    )

    for proc_key, proc in sorted_items:
        plugins: list[dict[str, Any]] = proc.get("plugins", [])
        priority: str = proc.get("priority", "normal")

        config = ProcessConfig(
            process_name=proc_key,
            plugins=list(plugins),   # копия списка — Dict at Boundary
            priority=priority,
        )
        process_configs.append(config)

    blueprint = SystemBlueprint(
        name=name,
        description=description,
        processes=process_configs,
        wires=[],   # Wire-связи между процессами не поддерживаются в UI пока
    )

    logger.info(
        "topology_to_blueprint: создан blueprint '%s' с %d процессами",
        name, len(process_configs),
    )
    return blueprint


def blueprint_to_topology(bp: SystemBlueprint) -> dict[str, dict]:
    """Конвертировать SystemBlueprint в dict для ProcessesSectionView.load_from_snapshot.

    Args:
        bp: SystemBlueprint с списком ProcessConfig.

    Returns:
        Словарь вида {"processes": {...}, "workers": {...}}.
        Для каждого процесса автоматически создаётся защищённый main-воркер
        (аналогично ProcessesSectionView.add_process).
    """
    processes: dict[str, dict] = {}
    workers: dict[str, dict] = {}

    for idx, proc_cfg in enumerate(bp.processes):
        proc_key = proc_cfg.process_name

        # Конвертируем ProcessConfig → dict-формат ProcessesSectionView
        processes[proc_key] = {
            "name": proc_key,
            "class_path": "",          # blueprint не хранит class_path
            "priority": proc_cfg.priority,
            "auto_start": True,
            "sort_order": idx,
            "plugins": list(proc_cfg.plugins),  # копия — Dict at Boundary
        }

        # Автоматически создаём protected main-воркер (как в add_process)
        worker_key = f"{proc_key}_main"
        workers[worker_key] = {
            "process_ref": proc_key,
            "name": "main",
            "worker_type": "router_poll",
            "enabled": True,
            "protected": True,
            "target_interval_ms": 0,
            "sort_order": 0,
        }

    logger.info(
        "blueprint_to_topology: конвертировано %d процессов из blueprint '%s'",
        len(processes), bp.name,
    )
    return {"processes": processes, "workers": workers}


def save_blueprint(bp: SystemBlueprint, path: Path) -> None:
    """Сохранить blueprint в JSON файл.

    Args:
        bp:   SystemBlueprint для сохранения.
        path: Путь к выходному JSON файлу (будет создан/перезаписан).

    Raises:
        OSError: При ошибке записи файла.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = bp.model_dump()

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info("save_blueprint: сохранён '%s' в %s", bp.name, path)


def load_blueprint(path: Path) -> SystemBlueprint:
    """Загрузить blueprint из JSON файла.

    Args:
        path: Путь к JSON файлу с ранее сохранённым SystemBlueprint.

    Returns:
        SystemBlueprint восстановленный из файла.

    Raises:
        FileNotFoundError: Если файл не найден.
        json.JSONDecodeError: Если файл содержит невалидный JSON.
        pydantic.ValidationError: Если JSON не соответствует схеме SystemBlueprint.
    """
    path = Path(path)

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    bp = SystemBlueprint.model_validate(data)

    logger.info("load_blueprint: загружен '%s' из %s", bp.name, path)
    return bp


__all__ = [
    "topology_to_blueprint",
    "blueprint_to_topology",
    "save_blueprint",
    "load_blueprint",
]
