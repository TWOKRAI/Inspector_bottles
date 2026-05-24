"""State Bootstrap — построение начального дерева состояния из topology и system config.

Используется для передачи initial_state в StateStoreManager при старте системы.
"""

from __future__ import annotations

from multiprocess_prototype.backend.state.schema import (
    STATE_DISPLAYS,
    STATE_PLUGINS,
    STATE_RECIPES,
    STATE_SERVICES,
)


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _build_process_entry(process_dict: dict) -> dict:
    """Построить запись процесса из одного элемента topology.processes.

    Args:
        process_dict: один элемент списка processes из topology YAML.

    Returns:
        dict с ключами "config" и "state".
    """
    # Конфиг берём из topology (плагины, chain_targets, priority)
    plugins = list(process_dict.get("plugins") or [])
    chain_targets = list(process_dict.get("chain_targets") or [])
    priority = process_dict.get("priority", "normal")

    config = {
        "plugins": plugins,
        "chain_targets": chain_targets,
        "priority": priority,
    }

    # Начальное runtime-состояние: всегда сбрасывается в "stopped"
    state = {
        "status": "stopped",
        "pid": None,
        "fps": 0.0,
        "frame_count": 0,
        "error": None,
    }

    return {"config": config, "state": state}


def _build_system_section(sys_config_dict: dict) -> dict:
    """Извлечь system-секцию из sys_config_dict.

    Args:
        sys_config_dict: результат SystemConfig().model_dump().

    Returns:
        dict с полями stop_timeout, shm_budget_mb, log_dir.
        При отсутствии секции — значения по умолчанию.
    """
    # Defaults совпадают с SystemSection defaults
    defaults = {
        "stop_timeout": 5.0,
        "shm_budget_mb": 512,
        "log_dir": "",
    }

    system_raw = sys_config_dict.get("system") or {}

    return {
        "stop_timeout": system_raw.get("stop_timeout", defaults["stop_timeout"]),
        "shm_budget_mb": system_raw.get("shm_budget_mb", defaults["shm_budget_mb"]),
        "log_dir": system_raw.get("log_dir", defaults["log_dir"]),
    }


def _build_wires_section(wires: list[dict]) -> dict:
    """Построить карту wire-ов из списка topology.wires.

    Ключ — "<source>-><target>", значение — dict с source, target, status.

    Args:
        wires: список wire-записей из topology YAML.

    Returns:
        dict вида {"<source>-><target>": {"source": ..., "target": ..., "status": "pending"}}.
    """
    result: dict[str, dict] = {}

    for wire in wires:
        source = wire.get("source", "")
        target = wire.get("target", "")
        key = f"{source}->{target}"

        # Статус при старте — pending (соединение ещё не установлено)
        result[key] = {
            "source": source,
            "target": target,
            "status": "pending",
        }

    return result


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------


def build_initial_state(topology_dict: dict, sys_config_dict: dict) -> dict:
    """Построить начальное дерево состояния из topology и system config.

    Args:
        topology_dict: результат yaml.safe_load (до валидации SystemBlueprint).
            Структура: {name, description, processes: [{process_name, plugins: [...],
            chain_targets: [...], priority}, ...], wires: [...]}
        sys_config_dict: результат SystemConfig().model_dump().
            Структура: {system: {stop_timeout, shm_budget_mb, log_dir}, camera: {...}, ...}

    Returns:
        dict вида:
        {
            "processes": {
                "<process_name>": {
                    "config": {
                        "plugins": [...],
                        "chain_targets": [...],
                        "priority": "normal",
                    },
                    "state": {
                        "status": "stopped",
                        "pid": None,
                        "fps": 0.0,
                        "frame_count": 0,
                        "error": None,
                    },
                },
                ...
            },
            "system": {
                "stop_timeout": 5.0,
                "shm_budget_mb": 512,
                "log_dir": "",
            },
            "wires": {
                "<source>-><target>": {
                    "source": "camera_0.capture.frame",
                    "target": "preprocessor.resize.frame",
                    "status": "pending",
                },
                ...
            },
            "services": {},                               # Phase 3 — реестр внешних сервисов
            "displays": {},                               # Phase 4 — дисплеи/окна вывода
            "recipes": {"active": None, "available": []}, # Phase 5 — рецепты инспекции
            "plugins": {"catalog": [], "paths": []},      # Phase 2 — каталог плагинов
        }
    """
    # Список процессов из topology (может быть None или пустым)
    processes_raw: list[dict] = list(topology_dict.get("processes") or [])

    # Строим словарь процессов: ключ — process_name
    processes: dict[str, dict] = {}
    for proc in processes_raw:
        name = proc.get("process_name", "")
        if not name:
            # Пропускаем записи без имени (некорректные)
            continue
        processes[name] = _build_process_entry(proc)

    # System-секция из конфига
    system = _build_system_section(sys_config_dict)

    # Wire-карта из topology
    wires_raw: list[dict] = list(topology_dict.get("wires") or [])
    wires = _build_wires_section(wires_raw)

    return {
        "processes": processes,
        "system": system,
        "wires": wires,
        # Phase 3+ — заглушечные ветки; наполняются данными в соответствующих фазах
        STATE_SERVICES: {},
        STATE_DISPLAYS: {},
        STATE_RECIPES: {"active": None, "available": []},
        STATE_PLUGINS: {"catalog": [], "paths": []},
    }
