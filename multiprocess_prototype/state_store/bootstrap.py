"""bootstrap.py — построение начального дерева состояния из AppConfig.

Принцип Dict at Boundary: принимаем app_config как dict (уже сконвертированный
через app_config.model_dump() или app_config.to_dict() вызывающей стороной).
Это позволяет работать без импорта AppConfig и Pydantic-зависимостей.
"""

from __future__ import annotations

# Поля ProcessLaunchConfig — инфраструктурные, не нужны в дереве состояния.
# Эти поля используются ProcessManager'ом для запуска процессов.
_PROCESS_INFRA_FIELDS: frozenset[str] = frozenset(
    {
        "process_name",
        "process_class",
        "priority",
        "auto_start",
        "dependencies",
        "queues",
        "log_dir",
        # SHM-специфика камеры — инфраструктура, не доменное состояние
        "memory",
        "ring_buffer_size",
        "shm_native_resolution",
        # Поля политики перезапуска
        "restart_policy",
        "restart_delay",
        "restart_max_retries",
    }
)


def _extract_domain_config(process_dict: dict) -> dict:
    """Извлечь доменные поля конфига, отфильтровав инфраструктурные.

    Args:
        process_dict: dict с полями конфига процесса (уже сериализованный).

    Returns:
        dict только с доменными полями (без process_name, process_class и т.д.).
    """
    return {k: v for k, v in process_dict.items() if k not in _PROCESS_INFRA_FIELDS}


def _build_camera_node(camera_dict: dict) -> dict:
    """Построить узел состояния для одной камеры.

    Args:
        camera_dict: dict с полями CameraConfig.

    Returns:
        dict с ключами config, state, regions.
    """
    return {
        "config": _extract_domain_config(camera_dict),
        "state": {
            "status": "stopped",
            "actual_fps": 0.0,
            "drops_count": 0,
            "last_frame_seq": 0,
        },
        # Регионы ROI — пустые при старте, заполняются позже из рецепта
        "regions": {},
    }


def _build_process_node(process_dict: dict) -> dict:
    """Построить узел состояния для процесса (renderer/robot/database).

    Args:
        process_dict: dict с полями конфига процесса.

    Returns:
        dict с ключами config, state.
    """
    return {
        "config": _extract_domain_config(process_dict),
        "state": {
            "status": "stopped",
        },
    }


def build_initial_state(app_config: dict) -> dict:
    """Построить начальное дерево состояния из конфигурации приложения.

    Принимает app_config как DICT (Dict at Boundary!), не как Pydantic-объект.
    Это позволяет работать без импорта AppConfig.

    Args:
        app_config: dict с ключами cameras, renderer, robot, database.
            cameras — list[dict], каждый dict содержит:
                camera_id: int, camera_type: str, fps: int,
                resolution_width: int, resolution_height: int, ...

    Returns:
        dict — начальное дерево состояния системы.

    Example::

        state = build_initial_state(app_config.model_dump())
        assert state["cameras"]["0"]["state"]["status"] == "stopped"
        assert state["system"]["status"] == "initializing"
    """
    # --- Раздел камер ---
    # Ключи — строки str(camera_id) для совместимости с PathStore и JSON
    cameras_section: dict[str, dict] = {}
    for camera_dict in app_config.get("cameras", []):
        camera_id = str(camera_dict.get("camera_id", 0))
        cameras_section[camera_id] = _build_camera_node(camera_dict)

    # --- Разделы остальных процессов ---
    renderer_section = _build_process_node(app_config.get("renderer", {}))
    robot_section = _build_process_node(app_config.get("robot", {}))
    database_section = _build_process_node(app_config.get("database", {}))

    # --- Системный раздел ---
    system_section: dict[str, str] = {
        "status": "initializing",
    }

    return {
        "cameras": cameras_section,
        "renderer": renderer_section,
        "robot": robot_section,
        "database": database_section,
        "system": system_section,
    }
