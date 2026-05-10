"""Конвертеры SystemTopology ↔ существующие форматы.

Мост между единой моделью SystemTopology и существующей инфраструктурой:
- SourceTopology (cameras/regions) для diff_topologies()
- ProcessConfigBridge._diff_snapshots() для processes/workers
- DisplayWindowManager для displays

Каждый конвертер работает с dict-представлениями (Dict at Boundary).
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, Dict, List, Optional

from ..sources.schemas import SourceTopology
from ..sources.topology_commands import diff_topologies, diff_to_commands

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Секция Sources: SystemTopology ↔ SourceTopology
# ---------------------------------------------------------------------------


def extract_source_topology(data: dict) -> SourceTopology:
    """Извлечь cameras/regions из SystemTopology dict → SourceTopology.

    Используется для вызова существующей diff_topologies().

    Args:
        data: SystemTopology.model_dump() или аналогичный dict.

    Returns:
        SourceTopology — совместим с diff_topologies().
    """
    return SourceTopology.model_validate({
        "cameras": data.get("cameras", {}),
        "regions": data.get("regions", {}),
    })


def inject_source_topology(data: dict, st: SourceTopology) -> dict:
    """Обновить cameras/regions секцию SystemTopology dict из SourceTopology.

    Обратная операция к extract_source_topology().

    Args:
        data: SystemTopology dict (модифицируется in-place, возвращается).
        st: SourceTopology с новыми данными.

    Returns:
        Обновлённый data dict.
    """
    dumped = st.model_dump()
    data["cameras"] = dumped.get("cameras", {})
    data["regions"] = dumped.get("regions", {})
    return data


def extract_source_commands(
    current: Optional[dict],
    desired: dict,
) -> List[Dict[str, Any]]:
    """Вычислить diff cameras/regions → команды для ProcessManager.

    Обёртка: extract_source_topology() → diff_topologies() → diff_to_commands().

    Args:
        current: Текущий SystemTopology dict (None = первый запуск).
        desired: Желаемый SystemTopology dict.

    Returns:
        Список команд: [{"cmd": "process.create", ...}, ...]
    """
    current_st = extract_source_topology(current) if current else None
    desired_st = extract_source_topology(desired)

    diff = diff_topologies(current_st, desired_st)
    if not diff.has_changes:
        return []

    return diff_to_commands(diff, desired_st)


# ---------------------------------------------------------------------------
# Секция Processes: diff + команды
# ---------------------------------------------------------------------------


def diff_process_configs(
    current: Optional[dict],
    desired: dict,
) -> Dict[str, Any]:
    """Вычислить diff processes/workers между текущим и желаемым состоянием.

    Логика реюзована из ProcessConfigBridge._diff_snapshots(), адаптирована
    для работы с SystemTopology dict.

    Args:
        current: Текущий SystemTopology dict (None = пустая система).
        desired: Желаемый SystemTopology dict.

    Returns:
        dict с ключами:
            processes_added:   list[str] — ключи новых процессов
            processes_removed: list[str] — ключи удалённых процессов
            workers_added:     list[str] — ключи новых воркеров
            workers_removed:   list[str] — ключи удалённых воркеров
            workers_modified:  list[str] — ключи изменённых воркеров
            has_changes:       bool
    """
    cur_procs = (current or {}).get("processes", {})
    des_procs = desired.get("processes", {})
    cur_workers = (current or {}).get("workers", {})
    des_workers = desired.get("workers", {})

    cur_proc_keys = set(cur_procs.keys())
    des_proc_keys = set(des_procs.keys())

    processes_added = sorted(des_proc_keys - cur_proc_keys)
    processes_removed = sorted(cur_proc_keys - des_proc_keys)

    cur_worker_keys = set(cur_workers.keys())
    des_worker_keys = set(des_workers.keys())

    workers_added = sorted(des_worker_keys - cur_worker_keys)
    workers_removed = sorted(cur_worker_keys - des_worker_keys)

    # Изменённые воркеры: проверяем target_interval_ms
    workers_modified: list[str] = []
    for wk in sorted(cur_worker_keys & des_worker_keys):
        cur_w = cur_workers[wk]
        des_w = des_workers[wk]
        # Сравниваем target_interval_ms
        if _get_interval(cur_w) != _get_interval(des_w):
            workers_modified.append(wk)

    has_changes = bool(
        processes_added or processes_removed
        or workers_added or workers_removed
        or workers_modified
    )

    return {
        "processes_added": processes_added,
        "processes_removed": processes_removed,
        "workers_added": workers_added,
        "workers_removed": workers_removed,
        "workers_modified": workers_modified,
        "has_changes": has_changes,
    }


def _get_interval(worker: dict) -> int:
    """Извлечь target_interval_ms из worker dict (plain dict или model_dump)."""
    if isinstance(worker, dict):
        return worker.get("target_interval_ms", 0)
    return getattr(worker, "target_interval_ms", 0)


def extract_process_commands(
    current: Optional[dict],
    desired: dict,
) -> List[Dict[str, Any]]:
    """Из diff processes/workers → список IPC-команд для ProcessManager.

    Порядок: stop removed → create added → reconfigure modified.
    Protected воркеры пропускаются при stop/create (они управляются вместе с процессом).

    Args:
        current: Текущий SystemTopology dict (None = пустая система).
        desired: Желаемый SystemTopology dict.

    Returns:
        Список команд: [{"cmd": "process.create", ...}, ...]
    """
    diff = diff_process_configs(current, desired)
    if not diff["has_changes"]:
        return []

    commands: list[dict[str, Any]] = []

    cur_procs = (current or {}).get("processes", {})
    des_procs = desired.get("processes", {})
    cur_workers = (current or {}).get("workers", {})
    des_workers = desired.get("workers", {})

    # 1. Stop удалённых процессов
    for proc_key in diff["processes_removed"]:
        proc = cur_procs[proc_key]
        name = proc.get("name", proc_key) if isinstance(proc, dict) else getattr(proc, "name", proc_key)
        commands.append({
            "cmd": "process.stop",
            "process_name": name,
        })

    # 2. Create новых процессов
    for proc_key in diff["processes_added"]:
        proc = des_procs[proc_key]
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
            "class_path": class_path,
            "priority": priority,
        })

    # 3. Stop удалённых воркеров (кроме protected)
    for wk in diff["workers_removed"]:
        w = cur_workers[wk]
        if isinstance(w, dict):
            if w.get("protected"):
                continue
            commands.append({
                "cmd": "worker.stop",
                "process_name": w.get("process_ref", ""),
                "worker_name": w.get("name", ""),
            })
        else:
            if getattr(w, "protected", False):
                continue
            commands.append({
                "cmd": "worker.stop",
                "process_name": getattr(w, "process_ref", ""),
                "worker_name": getattr(w, "name", ""),
            })

    # 4. Create новых воркеров (кроме protected — они создаются с процессом)
    for wk in diff["workers_added"]:
        w = des_workers[wk]
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

    # 5. Reconfigure: изменённый target_interval_ms
    for wk in diff["workers_modified"]:
        w = des_workers[wk]
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


# ---------------------------------------------------------------------------
# Секция Displays: diff
# ---------------------------------------------------------------------------


def extract_display_diff(
    current: Optional[dict],
    desired: dict,
) -> Dict[str, Any]:
    """Вычислить diff displays: added, removed, modified.

    Args:
        current: Текущий SystemTopology dict (None = пустая система).
        desired: Желаемый SystemTopology dict.

    Returns:
        dict с ключами:
            added:       dict[str, dict] — новые дисплеи {key: config}
            removed:     list[str] — ключи удалённых дисплеев
            modified:    dict[str, dict] — изменённые дисплеи {key: new_config}
            has_changes: bool
    """
    cur_displays = (current or {}).get("displays", {})
    des_displays = desired.get("displays", {})

    cur_keys = set(cur_displays.keys())
    des_keys = set(des_displays.keys())

    added_keys = sorted(des_keys - cur_keys)
    removed_keys = sorted(cur_keys - des_keys)

    # Изменённые: source_ref или fps_limit отличаются
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


# ---------------------------------------------------------------------------
# Секция Wires: diff + команды (Фаза 4 конструктора)
# ---------------------------------------------------------------------------


def diff_wire_configs(
    current: Optional[dict],
    desired: dict,
) -> Dict[str, Any]:
    """Вычислить diff wires между текущим и желаемым состоянием.

    Args:
        current: Текущий SystemTopology dict (None = первый запуск).
        desired: Желаемый SystemTopology dict.

    Returns:
        dict с ключами:
            wires_added:   list[str] — ключи новых wires
            wires_removed: list[str] — ключи удалённых wires
            wires_modified: list[str] — ключи изменённых wires
            has_changes:   bool
    """
    cur_wires = (current or {}).get("wires", {})
    des_wires = desired.get("wires", {})

    cur_keys = set(cur_wires.keys())
    des_keys = set(des_wires.keys())

    wires_added = sorted(des_keys - cur_keys)
    wires_removed = sorted(cur_keys - des_keys)

    # Изменённые: source, target, transport или shm_config отличаются
    wires_modified: list[str] = []
    _compare_fields = ("source", "target", "transport", "shm_config")
    for wk in sorted(cur_keys & des_keys):
        cur_w = cur_wires[wk]
        des_w = des_wires[wk]
        for field in _compare_fields:
            cur_val = cur_w.get(field) if isinstance(cur_w, dict) else getattr(cur_w, field, None)
            des_val = des_w.get(field) if isinstance(des_w, dict) else getattr(des_w, field, None)
            if cur_val != des_val:
                wires_modified.append(wk)
                break

    has_changes = bool(wires_added or wires_removed or wires_modified)

    return {
        "wires_added": wires_added,
        "wires_removed": wires_removed,
        "wires_modified": wires_modified,
        "has_changes": has_changes,
    }


def _parse_process_from_addr(addr: str) -> str:
    """Извлечь имя процесса ��з адреса 'process.plugin.port'."""
    parts = addr.split(".")
    return parts[0] if parts else ""


def _ensure_shm_defaults(wire_key: str, shm_config: dict, source_process: str) -> dict:
    """Заполнить пустые поля SHM-конфига дефолтами.

    Args:
        wire_key: Ключ wire (используется для авто-генерации shm_name).
        shm_config: Исходный shm_config dict (может быть пустым).
        source_process: Имя процесса-отправителя (дл�� owner_process).

    Returns:
        Новый dict с заполненными ��ефолтами.
    """
    result = dict(shm_config) if shm_config else {}
    if not result.get("shm_name"):
        result["shm_name"] = f"{wire_key}_shm"
    if not result.get("owner_process"):
        result["owner_process"] = source_process
    if "buffer_slots" not in result:
        result["buffer_slots"] = 4
    if not result.get("strategy"):
        result["strategy"] = "direct"
    return result


def extract_wire_commands(
    current: Optional[dict],
    desired: dict,
) -> List[Dict[str, Any]]:
    """Из diff wires → список IPC-команд для ProcessManager.

    Порядок: teardown removed → setup added → teardown+setup modified.

    Args:
        current: Текущий SystemTopology dict (None = первый запуск).
        desired: Желаемый SystemTopology dict.

    Returns:
        Список команд: [{"cmd": "wire.setup", ...}, {"cmd": "wire.teardown", ...}]
    """
    diff = diff_wire_configs(current, desired)
    if not diff["has_changes"]:
        return []

    commands: list[dict[str, Any]] = []

    cur_wires = (current or {}).get("wires", {})
    des_wires = desired.get("wires", {})

    # 1. Teardown удалённых wires
    for wk in diff["wires_removed"]:
        wire = cur_wires[wk]
        w = wire if isinstance(wire, dict) else wire.model_dump() if hasattr(wire, "model_dump") else {}
        source_proc = _parse_process_from_addr(w.get("source", ""))
        target_proc = _parse_process_from_addr(w.get("target", ""))
        commands.append({
            "cmd": "wire.teardown",
            "wire_key": wk,
            "source_process": source_proc,
            "target_process": target_proc,
            "shm_config": w.get("shm_config", {}),
        })

    # 2. Setup новых wires
    for wk in diff["wires_added"]:
        wire = des_wires[wk]
        w = wire if isinstance(wire, dict) else wire.model_dump() if hasattr(wire, "model_dump") else {}
        source_proc = _parse_process_from_addr(w.get("source", ""))
        target_proc = _parse_process_from_addr(w.get("target", ""))
        shm_config = _ensure_shm_defaults(wk, w.get("shm_config", {}), source_proc)
        commands.append({
            "cmd": "wire.setup",
            "wire_key": wk,
            "source": w.get("source", ""),
            "target": w.get("target", ""),
            "source_process": source_proc,
            "target_process": target_proc,
            "transport": w.get("transport", "router"),
            "shm_config": shm_config,
        })

    # 3. Modified wires: teardown старого + setup нового
    for wk in diff["wires_modified"]:
        # Teardown текущего
        cur_wire = cur_wires[wk]
        cw = cur_wire if isinstance(cur_wire, dict) else cur_wire.model_dump() if hasattr(cur_wire, "model_dump") else {}
        commands.append({
            "cmd": "wire.teardown",
            "wire_key": wk,
            "source_process": _parse_process_from_addr(cw.get("source", "")),
            "target_process": _parse_process_from_addr(cw.get("target", "")),
            "shm_config": cw.get("shm_config", {}),
        })
        # Setup нового
        des_wire = des_wires[wk]
        dw = des_wire if isinstance(des_wire, dict) else des_wire.model_dump() if hasattr(des_wire, "model_dump") else {}
        source_proc = _parse_process_from_addr(dw.get("source", ""))
        target_proc = _parse_process_from_addr(dw.get("target", ""))
        shm_config = _ensure_shm_defaults(wk, dw.get("shm_config", {}), source_proc)
        commands.append({
            "cmd": "wire.setup",
            "wire_key": wk,
            "source": dw.get("source", ""),
            "target": dw.get("target", ""),
            "source_process": source_proc,
            "target_process": target_proc,
            "transport": dw.get("transport", "router"),
            "shm_config": shm_config,
        })

    return commands


__all__ = [
    "extract_source_topology",
    "inject_source_topology",
    "extract_source_commands",
    "diff_process_configs",
    "extract_process_commands",
    "extract_display_diff",
    "diff_wire_configs",
    "extract_wire_commands",
]
