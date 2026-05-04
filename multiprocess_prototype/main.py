"""Inspector Prototype v3 — entry point (Blueprint-based).

Config-driven архитектура: SystemBlueprint определяет всю систему.
Процессы создаются через GenericProcess + плагины.
GUI остаётся специальным процессом (PySide6 event loop).
"""

import atexit
import logging
import sys
from pathlib import Path

_logger = logging.getLogger(__name__)

# Корень проекта (Inspector_bottles/) в sys.path для плоских импортов multiprocess_prototype.*
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# multiprocess_prototype/ в sys.path для плоских импортов внутри пакета
_proto_root = Path(__file__).resolve().parent
if str(_proto_root) not in sys.path:
    sys.path.insert(0, str(_proto_root))


def _load_profile():
    """Загрузить активный settings profile.

    Returns:
        SettingsProfile — валидированный профиль (fallback на дефолты при ошибке).
    """
    from pydantic import ValidationError

    from multiprocess_prototype.config.settings_profile import SettingsProfile
    from multiprocess_prototype.frontend.managers.settings_yaml_store import SettingsYamlStore

    store = SettingsYamlStore()
    data = store.read_dict() or {}
    current_id = data.get("current_profile", "default")
    profiles = data.get("profiles", {})
    profile_dict = profiles.get(current_id, {})

    try:
        return SettingsProfile.model_validate(profile_dict)
    except ValidationError as exc:
        _logger.warning(
            "Профиль '%s' невалиден, применяются defaults. Ошибки: %s",
            current_id, exc
        )
        return SettingsProfile()


def _build_camera_dicts(profile) -> list[dict]:
    """Построить список dict'ов камер из профиля."""
    from multiprocess_prototype.config.app import build_cameras_from_profile

    cameras = build_cameras_from_profile(
        camera_count=profile.camera_count,
        camera_source_type=profile.camera_source_type,
        ring_buffer_size=profile.ring_buffer_size,
    )
    return [c.model_dump() for c in cameras]


def main() -> int:
    from multiprocess_framework.modules.process_manager_module import SystemLauncher

    from multiprocess_prototype.backend.processes.gui.config import GuiConfig
    from multiprocess_prototype.backend.shm.cleanup import cleanup_stale_shm
    from multiprocess_prototype.plugins.manager import PluginManager
    from multiprocess_prototype.templates.default_system import build_default_blueprint

    # Auto-discovery: сканируем plugins/ и регистрируем все плагины
    plugin_manager = PluginManager(_proto_root / "plugins")
    discovery = plugin_manager.discover()
    _logger.info(
        "Плагины: %d загружено, %d новых в реестре",
        len(discovery.loaded), len(discovery.new_plugins)
    )

    profile = _load_profile()
    camera_dicts = _build_camera_dicts(profile)

    # Строим blueprint из профиля
    blueprint = build_default_blueprint(
        cameras=camera_dicts,
        worker_pool_size=profile.worker_pool_size,
    )

    # Валидация blueprint до запуска
    errors = blueprint.check()
    if errors:
        for err in errors:
            _logger.error("Blueprint error: %s", err)
        # Не прерываем — wires validation может быть неполным для service-плагинов
        # (у них inputs/outputs=[]), это ожидаемо

    # SHM cleanup
    shm_names = blueprint.shm_names()
    cleanup_stale_shm(known_names=shm_names)
    atexit.register(cleanup_stale_shm, shm_names)

    # GUI остаётся специальным процессом
    gui_camera_configs = [
        {
            "camera_id": c.get("camera_id", 0),
            "camera_type": c.get("camera_type", "simulator"),
            "process_name": f"camera_{c.get('camera_id', 0)}",
        }
        for c in camera_dicts
    ]
    gui = GuiConfig(
        camera_type=camera_dicts[0].get("camera_type", "simulator") if camera_dicts else "simulator",
        camera_configs=gui_camera_configs,
    )

    # Собираем app_config для оркестратора (StateStore bootstrap)
    app_config_dict = {
        "cameras": camera_dicts,
        "worker_pool_size": profile.worker_pool_size,
        "blueprint": blueprint.model_dump(),
    }

    from multiprocess_prototype.backend.processes.process_manager.process import (
        PROCESS_MANAGER_APP_CLASS_PATH,
    )

    launcher = SystemLauncher(
        stop_timeout=5.0,
        orchestrator_class_path=PROCESS_MANAGER_APP_CLASS_PATH,
        orchestrator_config={"app_config": app_config_dict},
    )

    # Добавляем процессы из blueprint (GenericProcess + плагины)
    for cfg in blueprint.build_configs():
        launcher.add_process(cfg.process_name, cfg.build())

    # GUI — отдельно (специальный процесс)
    from multiprocess_framework.modules.data_schema_module import process as process_fn
    launcher.add_process(*process_fn(gui))

    launcher.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
