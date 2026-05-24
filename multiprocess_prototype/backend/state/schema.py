"""State-tree контракт Inspector — единое место декларации всех ветвей.

Используется в Phase 0-5 как single source of truth для путей в StateStoreManager.
Каждая ветвь помечена фазой, в которой она начинает наполняться данными.

Допустимые поля процесса (processes.<name>.state.*):
    status       — строка: "stopped" | "running" | "error" | "paused"
    pid          — int или None: PID дочернего процесса
    fps          — float: кадровая частота (0.0 если не запущен)
    frame_count  — int: счётчик обработанных кадров
    error        — str или None: последнее сообщение об ошибке
    cpu_percent  — float: загрузка CPU процесса (Phase 1+)
    memory_mb    — float: потребление RAM в MB (Phase 1+)

Использование:
    from multiprocess_prototype.backend.state.schema import process_state_path
    path = process_state_path("camera_0", "status")
    # → "processes.camera_0.state.status"
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Корневые ветви — Phase 0 (processes, system, wires)
# ---------------------------------------------------------------------------

# Phase 0 — реестр запущенных процессов
STATE_PROCESSES = "processes"

# Phase 0 — системные параметры (timeout, бюджет SHM, директория логов)
STATE_SYSTEM = "system"

# Phase 0 — соединения между процессами (wire-карта)
STATE_WIRES = "wires"

# ---------------------------------------------------------------------------
# Корневые ветви — Phase 2+ (plugins, services, displays, recipes)
# ---------------------------------------------------------------------------

# Phase 2 — каталог плагинов и пути для динамической загрузки
STATE_PLUGINS = "plugins"

# Phase 3 — реестр внешних сервисов (камера, БД, Ollama и т.п.)
STATE_SERVICES = "services"

# Phase 4 — дисплеи/окна вывода (MultiDisplay-архитектура)
STATE_DISPLAYS = "displays"

# Phase 5 — рецепты инспекции (активный рецепт + каталог доступных)
STATE_RECIPES = "recipes"

# ---------------------------------------------------------------------------
# Статические пути system-уровня (Phase 0)
# ---------------------------------------------------------------------------

# Таймаут graceful-остановки процессов (секунды)
STATE_SYSTEM_STOP_TIMEOUT = "system.stop_timeout"

# Бюджет разделяемой памяти (мегабайты)
STATE_SYSTEM_SHM_BUDGET_MB = "system.shm_budget_mb"

# Директория для хранения логов
STATE_SYSTEM_LOG_DIR = "system.log_dir"

# ---------------------------------------------------------------------------
# Статические пути recipes/plugins (Phase 2, Phase 5)
# ---------------------------------------------------------------------------

# Текущий активный рецепт (имя или None)
STATE_RECIPES_ACTIVE = "recipes.active"

# Список доступных рецептов
STATE_RECIPES_AVAILABLE = "recipes.available"

# Каталог зарегистрированных плагинов (dict plugin_name → meta)
STATE_PLUGINS_CATALOG = "plugins.catalog"

# Пути для динамического поиска плагинов (list[str])
STATE_PLUGINS_PATHS = "plugins.paths"

# ---------------------------------------------------------------------------
# Helpers для path-композиции — пути с wildcards
# ---------------------------------------------------------------------------


def process_state_path(name: str, field: str) -> str:
    """Путь до runtime-поля процесса: processes.<name>.state.<field>.

    Пример:
        process_state_path("camera_0", "status")
        # → "processes.camera_0.state.status"
    """
    return f"processes.{name}.state.{field}"


def process_config_path(name: str, field: str) -> str:
    """Путь до config-поля процесса: processes.<name>.config.<field>.

    Пример:
        process_config_path("camera_0", "plugins")
        # → "processes.camera_0.config.plugins"
    """
    return f"processes.{name}.config.{field}"


def service_status_path(name: str) -> str:
    """Путь до статуса сервиса: services.<name>.status. (Phase 3)

    Пример:
        service_status_path("webcam_camera")
        # → "services.webcam_camera.status"
    """
    return f"services.{name}.status"


def service_config_path(name: str) -> str:
    """Путь до конфига сервиса: services.<name>.config. (Phase 3)

    Пример:
        service_config_path("webcam_camera")
        # → "services.webcam_camera.config"
    """
    return f"services.{name}.config"


def display_status_path(display_id: str) -> str:
    """Путь до статуса дисплея: displays.<display_id>.status. (Phase 4)

    Пример:
        display_status_path("main_window")
        # → "displays.main_window.status"
    """
    return f"displays.{display_id}.status"


def display_config_path(display_id: str) -> str:
    """Путь до конфига дисплея: displays.<display_id>.config. (Phase 4)

    Пример:
        display_config_path("main_window")
        # → "displays.main_window.config"
    """
    return f"displays.{display_id}.config"


def wire_path(key: str, field: str) -> str:
    """Путь до поля wire-соединения: wires.<key>.<field>.

    Пример:
        wire_path("camera_0.capture.frame->preprocessor.resize.frame", "status")
        # → "wires.camera_0.capture.frame->preprocessor.resize.frame.status"
    """
    return f"wires.{key}.{field}"
