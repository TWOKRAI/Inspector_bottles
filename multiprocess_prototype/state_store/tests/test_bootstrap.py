"""Тесты для state_store/bootstrap.py — build_initial_state().

Все тесты работают с plain dict (без импорта AppConfig/Pydantic).
"""

from __future__ import annotations

from state_store.bootstrap import build_initial_state

# ---------------------------------------------------------------------------
# Вспомогательные фабрики тестовых данных
# ---------------------------------------------------------------------------


def _make_camera(camera_id: int, camera_type: str = "simulator", fps: int = 25) -> dict:
    """Создать минимальный dict камеры для тестов."""
    return {
        "camera_id": camera_id,
        "camera_type": camera_type,
        "fps": fps,
        "resolution_width": 640,
        "resolution_height": 480,
        "device_id": 0,
        # Инфраструктурные поля — должны быть отфильтрованы
        "process_name": f"camera_{camera_id}",
        "process_class": "some.module.CameraProcess",
        "priority": "high",
        "ring_buffer_size": 3,
        "shm_native_resolution": False,
    }


def _make_app_config(cameras: list[dict] | None = None) -> dict:
    """Создать минимальный app_config для тестов."""
    return {
        "cameras": cameras or [],
        "renderer": {
            "show_original": False,
            "show_bbox": True,
            "process_name": "renderer",
            "process_class": "some.module.RendererProcess",
        },
        "robot": {
            "log_file": "./robot.log",
            "reject_delay": 0.5,
            "process_name": "robot",
            "process_class": "some.module.RobotProcess",
        },
        "database": {
            "db_url": "sqlite:///inspector.db",
            "db_dialect": "sqlite",
            "batch_size": 50,
            "process_name": "database",
            "process_class": "some.module.DatabaseProcess",
        },
    }


# ---------------------------------------------------------------------------
# Тест 1: структура верхнего уровня
# ---------------------------------------------------------------------------


def test_top_level_keys_present():
    """Дерево состояния содержит все обязательные разделы верхнего уровня."""
    state = build_initial_state(_make_app_config())

    assert "cameras" in state, "Раздел cameras отсутствует"
    assert "renderer" in state, "Раздел renderer отсутствует"
    assert "robot" in state, "Раздел robot отсутствует"
    assert "database" in state, "Раздел database отсутствует"
    assert "system" in state, "Раздел system отсутствует"


# ---------------------------------------------------------------------------
# Тест 2: system.status = "initializing"
# ---------------------------------------------------------------------------


def test_system_status_initializing():
    """system.status должен быть 'initializing' при старте."""
    state = build_initial_state(_make_app_config())
    assert state["system"]["status"] == "initializing"


# ---------------------------------------------------------------------------
# Тест 3: две камеры → ключи "0" и "1" (строки)
# ---------------------------------------------------------------------------


def test_two_cameras_string_keys():
    """AppConfig с 2 камерами → cameras.0 и cameras.1 с строковыми ключами."""
    cameras = [
        _make_camera(camera_id=0, camera_type="webcam", fps=30),
        _make_camera(camera_id=1, camera_type="hikvision", fps=25),
    ]
    state = build_initial_state(_make_app_config(cameras=cameras))

    assert "0" in state["cameras"], "Ключ '0' (строка) отсутствует в cameras"
    assert "1" in state["cameras"], "Ключ '1' (строка) отсутствует в cameras"
    # Убеждаемся что ключи именно строки, а не int
    assert 0 not in state["cameras"], "Ключ 0 (int) не должен быть в cameras"


# ---------------------------------------------------------------------------
# Тест 4: структура узла камеры (config + state + regions)
# ---------------------------------------------------------------------------


def test_camera_node_structure():
    """Каждая камера имеет подразделы config, state, regions."""
    cameras = [_make_camera(camera_id=0)]
    state = build_initial_state(_make_app_config(cameras=cameras))
    camera_node = state["cameras"]["0"]

    assert "config" in camera_node, "Подраздел config отсутствует у камеры"
    assert "state" in camera_node, "Подраздел state отсутствует у камеры"
    assert "regions" in camera_node, "Подраздел regions отсутствует у камеры"


# ---------------------------------------------------------------------------
# Тест 5: инфраструктурные поля отфильтрованы из config камеры
# ---------------------------------------------------------------------------


def test_camera_config_filters_infra_fields():
    """process_name, process_class, priority, ring_buffer_size, shm_native_resolution
    не должны попасть в config узла камеры."""
    cameras = [_make_camera(camera_id=0)]
    state = build_initial_state(_make_app_config(cameras=cameras))
    cam_config = state["cameras"]["0"]["config"]

    infra_fields = {"process_name", "process_class", "priority", "ring_buffer_size", "shm_native_resolution"}
    for field in infra_fields:
        assert field not in cam_config, f"Инфраструктурное поле '{field}' не должно быть в config камеры"


# ---------------------------------------------------------------------------
# Тест 6: доменные поля камеры присутствуют в config
# ---------------------------------------------------------------------------


def test_camera_config_contains_domain_fields():
    """Доменные поля (camera_type, fps, resolution_width и т.д.) должны быть в config."""
    cameras = [_make_camera(camera_id=0, camera_type="webcam", fps=30)]
    state = build_initial_state(_make_app_config(cameras=cameras))
    cam_config = state["cameras"]["0"]["config"]

    assert cam_config["camera_type"] == "webcam"
    assert cam_config["fps"] == 30
    assert cam_config["resolution_width"] == 640
    assert cam_config["resolution_height"] == 480
    assert cam_config["camera_id"] == 0


# ---------------------------------------------------------------------------
# Тест 7: начальное состояние камеры
# ---------------------------------------------------------------------------


def test_camera_initial_state_values():
    """state камеры: status='stopped', actual_fps=0.0, drops_count=0, last_frame_seq=0."""
    cameras = [_make_camera(camera_id=0)]
    state = build_initial_state(_make_app_config(cameras=cameras))
    cam_state = state["cameras"]["0"]["state"]

    assert cam_state["status"] == "stopped"
    assert cam_state["actual_fps"] == 0.0
    assert cam_state["drops_count"] == 0
    assert cam_state["last_frame_seq"] == 0


# ---------------------------------------------------------------------------
# Тест 8: regions камеры — пустой dict
# ---------------------------------------------------------------------------


def test_camera_regions_empty():
    """regions камеры должен быть пустым dict при инициализации."""
    cameras = [_make_camera(camera_id=0)]
    state = build_initial_state(_make_app_config(cameras=cameras))

    assert state["cameras"]["0"]["regions"] == {}


# ---------------------------------------------------------------------------
# Тест 9: renderer имеет config и state
# ---------------------------------------------------------------------------


def test_renderer_node_structure_and_state():
    """renderer содержит config с доменными полями и state.status='stopped'."""
    state = build_initial_state(_make_app_config())
    renderer = state["renderer"]

    assert "config" in renderer
    assert "state" in renderer
    assert renderer["state"]["status"] == "stopped"
    # process_name не должен попасть в config renderer
    assert "process_name" not in renderer["config"]
    assert "process_class" not in renderer["config"]
    # Доменные поля renderer присутствуют
    assert "show_original" in renderer["config"]
    assert "show_bbox" in renderer["config"]


# ---------------------------------------------------------------------------
# Тест 10: robot и database имеют config и state
# ---------------------------------------------------------------------------


def test_robot_and_database_node_structure():
    """robot и database содержат config (доменные поля) и state.status='stopped'."""
    state = build_initial_state(_make_app_config())

    # Robot
    assert state["robot"]["state"]["status"] == "stopped"
    assert "process_name" not in state["robot"]["config"]
    assert "log_file" in state["robot"]["config"]
    assert "reject_delay" in state["robot"]["config"]

    # Database
    assert state["database"]["state"]["status"] == "stopped"
    assert "process_name" not in state["database"]["config"]
    assert "db_url" in state["database"]["config"]
    assert "batch_size" in state["database"]["config"]


# ---------------------------------------------------------------------------
# Тест 11: пустой список камер → пустой cameras dict
# ---------------------------------------------------------------------------


def test_empty_cameras_list():
    """Если cameras=[] → state['cameras'] == {}."""
    state = build_initial_state(_make_app_config(cameras=[]))
    assert state["cameras"] == {}


# ---------------------------------------------------------------------------
# Тест 12: отсутствующие разделы в app_config не вызывают ошибку
# ---------------------------------------------------------------------------


def test_missing_sections_no_error():
    """Если в app_config нет renderer/robot/database — функция не падает."""
    minimal_config = {"cameras": [_make_camera(0)]}
    state = build_initial_state(minimal_config)

    # Разделы должны быть в дереве даже если пустые в конфиге
    assert "renderer" in state
    assert "robot" in state
    assert "database" in state
    # Конфиги пустые, но state присутствует
    assert state["renderer"]["state"]["status"] == "stopped"
