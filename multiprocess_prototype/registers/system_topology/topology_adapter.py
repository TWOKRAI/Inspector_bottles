"""
Unified Topology Adapter для TopologyManager.

Предоставляет diff_fn и commands_fn для SystemTopology (вся топология системы),
реюзая существующие функции из topology_commands.py и converters.py.

Использование (в ProcessManagerProcess при инициализации):
    from multiprocess_prototype.registers.system_topology.topology_adapter import (
        configure_topology_manager,
    )
    configure_topology_manager(self._topology_manager)

После этого вызов topology_manager.apply(system_topology_dict) выполнит
полный diff + генерацию команд для всех секций SystemTopology.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..sources.topology_commands import diff_to_commands, diff_topologies
from .converters import (
    diff_process_configs,
    extract_process_commands,
    extract_source_topology,
)

if TYPE_CHECKING:
    from multiprocess_framework.modules.process_manager_module.process.topology_manager import (
        TopologyManager,
    )

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# system_diff_fn — unified diff SystemTopology
# ---------------------------------------------------------------------------


def system_diff_fn(current: Optional[dict], desired: dict) -> dict:
    """Unified diff SystemTopology → структура для system_commands_fn.

    Декомпозирует SystemTopology на секции и вычисляет diff по каждой:
    - cameras/regions  → TopologyDiff через diff_topologies()
    - processes/workers → через diff_process_configs()
    - displays         → простое ключевое сравнение

    Args:
        current: Текущий SystemTopology dict (None = первый запуск, пустая система).
        desired: Желаемый SystemTopology dict.

    Returns:
        {
            "has_changes": bool,
            "source_diff": TopologyDiff — diff cameras/regions (объект),
            "process_diff": {
                "processes_added":   list[str],
                "processes_removed": list[str],
                "workers_added":     list[str],
                "workers_removed":   list[str],
                "workers_modified":  list[str],
                "has_changes":       bool,
            },
            "display_diff": {
                "added":      dict[str, dict],
                "removed":    list[str],
                "modified":   dict[str, dict],
                "has_changes": bool,
            },
        }
    """
    # --- Секция Sources: cameras / regions ---
    current_st = extract_source_topology(current) if current else None
    desired_st = extract_source_topology(desired)
    source_diff = diff_topologies(current_st, desired_st)

    # --- Секция Processes: processes / workers ---
    process_diff = diff_process_configs(current, desired)

    # --- Секция Displays ---
    display_diff = _diff_displays(current, desired)

    has_changes = (
        source_diff.has_changes
        or process_diff["has_changes"]
        or display_diff["has_changes"]
    )

    logger.debug(
        "system_diff_fn: has_changes=%s "
        "(sources=%s, processes=%s, displays=%s)",
        has_changes,
        source_diff.has_changes,
        process_diff["has_changes"],
        display_diff["has_changes"],
    )

    return {
        "has_changes": has_changes,
        "source_diff": source_diff,
        "process_diff": process_diff,
        "display_diff": display_diff,
    }


# ---------------------------------------------------------------------------
# system_commands_fn — unified генерация команд из diff
# ---------------------------------------------------------------------------


def system_commands_fn(diff: dict, desired: dict) -> list[dict]:
    """Unified генерация команд из diff для TopologyManager.

    Порядок критичен:
    1. stop: удалённые процессы (process.stop)
    2. stop: удалённые воркеры (worker.stop)
    3. create: новые процессы (process.create)
    4. create: новые воркеры (worker.create)
    5. reconfigure: изменённые воркеры (worker.set_interval)
    6. camera/region lifecycle: stop → create → reconfigure (через diff_to_commands)

    Note: worker.* команды пока не обрабатываются TopologyManager._execute_command
    (вернут unknown). Обработчик подключается в Task 3.2.
    Подробнее: TopologyManager._execute_command в topology_manager.py.

    Args:
        diff: Результат system_diff_fn().
        desired: Желаемый SystemTopology dict.

    Returns:
        Список команд для TopologyManager._execute_command.
    """
    if not diff.get("has_changes", False):
        return []

    commands: list[dict[str, Any]] = []

    # --- Процессы и воркеры (секция processes) ---
    process_cmds = _build_process_commands(diff.get("process_diff", {}), desired)
    commands.extend(process_cmds)

    # --- Cameras/regions (секция sources) ---
    source_diff = diff.get("source_diff")
    if source_diff is not None and source_diff.has_changes:
        desired_st = extract_source_topology(desired)
        camera_cmds = diff_to_commands(source_diff, desired_st)
        commands.extend(camera_cmds)

    logger.debug(
        "system_commands_fn: %d команд итого "
        "(process_cmds=%d, camera_cmds=%d)",
        len(commands),
        len(process_cmds),
        len(commands) - len(process_cmds),
    )

    return commands


# ---------------------------------------------------------------------------
# configure_topology_manager — хелпер конфигурирования TopologyManager
# ---------------------------------------------------------------------------


def configure_topology_manager(topology_manager: "TopologyManager") -> None:
    """Сконфигурировать TopologyManager для работы с SystemTopology.

    Устанавливает diff_fn и commands_fn через topology_manager.configure().
    Вызывать при инициализации ProcessManagerProcess в прототипе.

    Вариант A (чистый): не трогаем фреймворк — передаём callback'и через
    существующий API configure().

    Args:
        topology_manager: Экземпляр TopologyManager из ProcessManagerProcess.

    Example:
        # В ProcessManagerProcess.__init__() или setup():
        from multiprocess_prototype.registers.system_topology.topology_adapter import (
            configure_topology_manager,
        )
        configure_topology_manager(self._topology_manager)
    """
    topology_manager.configure(
        diff_fn=system_diff_fn,
        commands_fn=system_commands_fn,
    )
    logger.info(
        "TopologyManager сконфигурирован для SystemTopology "
        "(diff_fn=system_diff_fn, commands_fn=system_commands_fn)"
    )


# ---------------------------------------------------------------------------
# Приватные хелперы
# ---------------------------------------------------------------------------


def _diff_displays(current: Optional[dict], desired: dict) -> Dict[str, Any]:
    """Вычислить diff секции displays.

    Args:
        current: Текущий SystemTopology dict (None = пустая система).
        desired: Желаемый SystemTopology dict.

    Returns:
        dict с ключами: added, removed, modified, has_changes.
    """
    cur_displays: dict = (current or {}).get("displays", {})
    des_displays: dict = desired.get("displays", {})

    cur_keys = set(cur_displays.keys())
    des_keys = set(des_displays.keys())

    added_keys = sorted(des_keys - cur_keys)
    removed_keys = sorted(cur_keys - des_keys)

    # Изменённые: любое поле отличается
    modified: dict[str, dict] = {}
    for dk in sorted(cur_keys & des_keys):
        cur_d = cur_displays[dk]
        des_d = des_displays[dk]
        if cur_d != des_d:
            modified[dk] = des_d if isinstance(des_d, dict) else des_d

    added = {k: des_displays[k] for k in added_keys}
    has_changes = bool(added or removed_keys or modified)

    return {
        "added": added,
        "removed": removed_keys,
        "modified": modified,
        "has_changes": has_changes,
    }


def _build_process_commands(
    process_diff: dict,
    desired: dict,
) -> List[Dict[str, Any]]:
    """Сгенерировать команды для процессов/воркеров из process_diff.

    Реюзает extract_process_commands() из converters.py, передавая текущий
    желаемый dict как desired и None как current (т.к. diff уже вычислен).

    Альтернативный подход — вызываем extract_process_commands напрямую,
    передавая только желаемый dict, поскольку diff уже вычислен в system_diff_fn.

    Порядок: stop removed → create added → reconfigure modified.

    Note: Отдельные worker.* команды (worker.stop, worker.create, worker.set_interval)
    возвращаются как есть — обработчик в TopologyManager._execute_command
    будет добавлен в Task 3.2.
    """
    if not process_diff.get("has_changes", False):
        return []

    # Реюзаем готовую логику из converters.py
    # extract_process_commands() принимает (current, desired) и вычисляет diff+команды.
    # Здесь мы передаём None как current и desired — чтобы получить только команды
    # из уже известного process_diff. Но это дублировало бы diff-вычисление.
    #
    # Правильный подход: передаём process_diff напрямую в _build_from_diff(),
    # не вызывая extract_process_commands (она бы пересчитала diff).
    # Вместо этого реконструируем команды из process_diff напрямую.
    commands: list[dict[str, Any]] = []

    des_procs: dict = desired.get("processes", {})
    des_workers: dict = desired.get("workers", {})

    processes_removed: list[str] = process_diff.get("processes_removed", [])
    processes_added: list[str] = process_diff.get("processes_added", [])
    workers_removed: list[str] = process_diff.get("workers_removed", [])
    workers_added: list[str] = process_diff.get("workers_added", [])
    workers_modified: list[str] = process_diff.get("workers_modified", [])

    # 1. Stop удалённых процессов
    for proc_key in processes_removed:
        # Имя процесса берём из process_diff — current уже недоступен здесь,
        # используем proc_key как fallback (в реальной системе имя = ключ)
        commands.append({
            "cmd": "process.stop",
            "process_name": proc_key,
        })

    # 2. Stop удалённых воркеров (кроме protected — они управляются вместе с процессом)
    for wk_key in workers_removed:
        # Воркер уже удалён из desired — данные недоступны, используем ключ
        commands.append({
            "cmd": "worker.stop",
            "worker_key": wk_key,
        })

    # 3. Create новых процессов
    for proc_key in processes_added:
        proc = des_procs.get(proc_key, {})
        if isinstance(proc, dict):
            name = proc.get("name", proc_key)
            class_path = proc.get("class_path", "")
            priority = proc.get("priority", "normal")
        else:
            name = getattr(proc, "name", proc_key)
            class_path = getattr(proc, "class_path", "")
            priority = getattr(proc, "priority", "normal")

        commands.append({
            "cmd": "process.create",
            "process_name": name,
            "proc_dict": {
                "class": class_path,
                "config": {"process_name": name},
                "priority": priority,
            },
        })

    # 4. Create новых воркеров (кроме protected)
    for wk_key in workers_added:
        w = des_workers.get(wk_key, {})
        if isinstance(w, dict):
            if w.get("protected"):
                continue
            commands.append({
                "cmd": "worker.create",
                "process_name": w.get("process_ref", ""),
                "worker_name": w.get("name", ""),
                "worker_type": w.get("worker_type", "custom"),
                "target_interval_ms": w.get("target_interval_ms", 0),
            })
        else:
            if getattr(w, "protected", False):
                continue
            commands.append({
                "cmd": "worker.create",
                "process_name": getattr(w, "process_ref", ""),
                "worker_name": getattr(w, "name", ""),
                "worker_type": getattr(w, "worker_type", "custom"),
                "target_interval_ms": getattr(w, "target_interval_ms", 0),
            })

    # 5. Reconfigure: изменённые воркеры (target_interval_ms)
    for wk_key in workers_modified:
        w = des_workers.get(wk_key, {})
        if isinstance(w, dict):
            commands.append({
                "cmd": "worker.set_interval",
                "process_name": w.get("process_ref", ""),
                "worker_name": w.get("name", ""),
                "target_interval_ms": w.get("target_interval_ms", 0),
            })
        else:
            commands.append({
                "cmd": "worker.set_interval",
                "process_name": getattr(w, "process_ref", ""),
                "worker_name": getattr(w, "name", ""),
                "target_interval_ms": getattr(w, "target_interval_ms", 0),
            })

    return commands


__all__ = [
    "system_diff_fn",
    "system_commands_fn",
    "configure_topology_manager",
]
