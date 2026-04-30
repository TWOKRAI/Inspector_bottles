"""Inspector Prototype v3 — entry point.

Phase 3: поддержка N гетерогенных камер из settings profile / рецепта.
"""

import atexit
import sys
from pathlib import Path

# Корень проекта (Inspector_bottles/) в sys.path для плоских импортов multiprocess_prototype.* —
# проектный пакет не установлен через pip, поэтому путь добавляется явно.
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# multiprocess_prototype/ в sys.path для плоских импортов внутри пакета
# (backend.routing.*, registers.display.* и т.д. используют короткие пути).
_proto_root = Path(__file__).resolve().parent
if str(_proto_root) not in sys.path:
    sys.path.insert(0, str(_proto_root))


def _load_cameras_from_profile():
    """Загрузить список камер и worker_pool_size из активного settings profile.

    Профиль валидируется через SettingsProfile. При невалидных данных — fallback
    на дефолтный профиль с предупреждением в stdout.

    Returns:
        tuple (cameras, worker_pool_size)
    """
    from pydantic import ValidationError

    from multiprocess_prototype.config.app import build_cameras_from_profile
    from multiprocess_prototype.config.settings_profile import SettingsProfile
    from multiprocess_prototype.frontend.managers.settings_yaml_store import SettingsYamlStore

    store = SettingsYamlStore()
    data = store.read_dict() or {}
    current_id = data.get("current_profile", "default")
    profiles = data.get("profiles", {})
    profile_dict = profiles.get(current_id, {})

    # Валидируем профиль — при ошибке fallback на дефолты
    try:
        profile = SettingsProfile.model_validate(profile_dict)
    except ValidationError as exc:
        print(
            f"WARNING: профиль '{current_id}' содержит невалидные значения, "
            f"применяются defaults. Ошибки: {exc}"
        )
        profile = SettingsProfile()

    cameras = build_cameras_from_profile(
        camera_count=profile.camera_count,
        camera_source_type=profile.camera_source_type,
        ring_buffer_size=profile.ring_buffer_size,
    )

    # Phase 5c: количество worker-процессов в пуле (0 = отключён)
    worker_pool_size = profile.worker_pool_size

    return cameras, worker_pool_size


def main() -> int:
    from multiprocess_framework.modules.data_schema_module import process
    from multiprocess_framework.modules.process_manager_module import SystemLauncher

    from multiprocess_prototype.backend.processes.gui.config import GuiConfig
    from multiprocess_prototype.backend.shm.cleanup import cleanup_stale_shm
    from multiprocess_prototype.config import AppConfig

    cameras, worker_pool_size = _load_cameras_from_profile()

    # Передаём информацию о камерах в GuiConfig для frontend CameraRegistry
    camera_dicts = [
        {"camera_id": c.camera_id, "camera_type": c.camera_type, "process_name": c.process_name}
        for c in cameras
    ]
    gui = GuiConfig(
        camera_type=cameras[0].camera_type if cameras else "simulator",
        camera_configs=camera_dicts,
    )

    app = AppConfig(cameras=cameras, gui=gui, worker_pool_size=worker_pool_size)

    # P11: очистка осиротевших SHM-сегментов от предыдущих аварийных запусков
    shm_names = app.all_shm_names()
    cleanup_stale_shm(known_names=shm_names)

    # P11: safety net — повторная очистка при нормальном завершении (atexit)
    atexit.register(cleanup_stale_shm, shm_names)

    from multiprocess_prototype.backend.processes.process_manager.process import (
        PROCESS_MANAGER_APP_CLASS_PATH,
    )

    launcher = SystemLauncher(
        stop_timeout=app.stop_timeout,
        orchestrator_class_path=PROCESS_MANAGER_APP_CLASS_PATH,
    )
    for cfg in app.all_process_configs():
        launcher.add_process(*process(cfg))
    launcher.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
