"""Тесты для state-tree schema — константы и helper-функции путей."""

from multiprocess_prototype.backend.state.schema import (
    STATE_DISPLAYS,
    STATE_PLUGINS,
    STATE_PLUGINS_CATALOG,
    STATE_PLUGINS_PATHS,
    STATE_PROCESSES,
    STATE_RECIPES,
    STATE_RECIPES_ACTIVE,
    STATE_RECIPES_AVAILABLE,
    STATE_SERVICES,
    STATE_SYSTEM,
    STATE_SYSTEM_LOG_DIR,
    STATE_SYSTEM_SHM_BUDGET_MB,
    STATE_SYSTEM_STOP_TIMEOUT,
    STATE_WIRES,
    display_config_path,
    display_status_path,
    process_config_path,
    process_state_path,
    service_config_path,
    service_status_path,
    wire_path,
)


# ---------------------------------------------------------------------------
# Тест 1: Корневые константы ветвей — непустые строки
# ---------------------------------------------------------------------------


def test_root_branch_constants_are_non_empty_strings():
    """Все корневые ветви — непустые строковые константы."""
    roots = [
        STATE_PROCESSES,
        STATE_SYSTEM,
        STATE_WIRES,
        STATE_PLUGINS,
        STATE_SERVICES,
        STATE_DISPLAYS,
        STATE_RECIPES,
    ]
    for constant in roots:
        assert isinstance(constant, str), f"Ожидалась строка, получено {type(constant)}"
        assert len(constant) > 0, f"Константа пустая: {constant!r}"


# ---------------------------------------------------------------------------
# Тест 2: Статические пути system/recipes/plugins — корректный формат
# ---------------------------------------------------------------------------


def test_static_paths_format():
    """Статические пути содержат точку как разделитель и начинаются с корня."""
    assert STATE_SYSTEM_STOP_TIMEOUT == "system.stop_timeout"
    assert STATE_SYSTEM_SHM_BUDGET_MB == "system.shm_budget_mb"
    assert STATE_SYSTEM_LOG_DIR == "system.log_dir"
    assert STATE_RECIPES_ACTIVE == "recipes.active"
    assert STATE_RECIPES_AVAILABLE == "recipes.available"
    assert STATE_PLUGINS_CATALOG == "plugins.catalog"
    assert STATE_PLUGINS_PATHS == "plugins.paths"


# ---------------------------------------------------------------------------
# Тест 3: process_state_path — acceptance criteria из ТЗ
# ---------------------------------------------------------------------------


def test_process_state_path_acceptance_criteria():
    """process_state_path('camera_0', 'status') → 'processes.camera_0.state.status'."""
    result = process_state_path("camera_0", "status")
    assert result == "processes.camera_0.state.status"


def test_process_state_path_various_fields():
    """process_state_path корректно формирует пути для разных полей."""
    assert process_state_path("gui", "pid") == "processes.gui.state.pid"
    assert process_state_path("preprocessor", "fps") == "processes.preprocessor.state.fps"
    assert process_state_path("camera_0", "error") == "processes.camera_0.state.error"


# ---------------------------------------------------------------------------
# Тест 4: process_config_path
# ---------------------------------------------------------------------------


def test_process_config_path():
    """process_config_path формирует путь до config-поля процесса."""
    assert process_config_path("camera_0", "plugins") == "processes.camera_0.config.plugins"
    assert process_config_path("gui", "priority") == "processes.gui.config.priority"
    assert process_config_path("preprocessor", "chain_targets") == "processes.preprocessor.config.chain_targets"


# ---------------------------------------------------------------------------
# Тест 5: service_status_path и service_config_path (Phase 3)
# ---------------------------------------------------------------------------


def test_service_paths():
    """Helpers сервисов дают корректные пути (Phase 3)."""
    assert service_status_path("webcam_camera") == "services.webcam_camera.status"
    assert service_config_path("webcam_camera") == "services.webcam_camera.config"
    assert service_status_path("database") == "services.database.status"


# ---------------------------------------------------------------------------
# Тест 6: display_status_path и display_config_path (Phase 4)
# ---------------------------------------------------------------------------


def test_display_paths():
    """Helpers дисплеев дают корректные пути (Phase 4)."""
    assert display_status_path("main_window") == "displays.main_window.status"
    assert display_config_path("main_window") == "displays.main_window.config"
    assert display_status_path("overlay_1") == "displays.overlay_1.status"


# ---------------------------------------------------------------------------
# Тест 7: wire_path
# ---------------------------------------------------------------------------


def test_wire_path():
    """wire_path формирует путь до поля wire-соединения."""
    key = "camera_0.capture.frame->preprocessor.resize.frame"
    assert wire_path(key, "status") == f"wires.{key}.status"
    assert wire_path(key, "source") == f"wires.{key}.source"
