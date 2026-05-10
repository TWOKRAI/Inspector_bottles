"""Demo: GenericProcess + плагины.

Загружает SystemBlueprint (SchemaBase-чертёж), валидирует и передаёт в ProcessManager.

Запуск: python multiprocess_prototype/demo_generic.py
"""

import atexit
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

_proto_root = Path(__file__).resolve().parent
if str(_proto_root) not in sys.path:
    sys.path.insert(0, str(_proto_root))


def main() -> int:
    from multiprocess_framework.modules.data_schema_module import process
    from multiprocess_framework.modules.process_manager_module import SystemLauncher

    # Импортируем плагины чтобы они зарегистрировались в PluginRegistry
    import multiprocess_prototype.backend.plugins.capture.plugin  # noqa: F401
    import multiprocess_prototype.backend.plugins.color_mask.plugin  # noqa: F401
    import multiprocess_prototype.backend.plugins.render.plugin  # noqa: F401

    from multiprocess_prototype.backend.plugins.blueprints.demo_color_mask import BLUEPRINT
    from multiprocess_prototype.backend.processes.gui.config import GuiConfig
    from multiprocess_prototype.backend.processes.process_manager.process import (
        PROCESS_MANAGER_APP_CLASS_PATH,
    )
    from multiprocess_prototype.backend.shm.cleanup import cleanup_stale_shm

    # Валидация чертежа до запуска
    errors = BLUEPRINT.check()
    if errors:
        print("[demo] Ошибки валидации чертежа:")
        for e in errors:
            print(f"  \u2717 {e}")
        return 1

    # Чертёж → конфиги
    configs = BLUEPRINT.build_configs()

    # GUI — классический процесс
    gui = GuiConfig(
        camera_type="webcam",
        camera_configs=[{
            "camera_id": 0,
            "camera_type": "webcam",
            "process_name": "camera_0",
        }],
    )
    all_configs = [*configs, gui]

    # SHM cleanup
    shm_names = BLUEPRINT.shm_names()
    cleanup_stale_shm(known_names=shm_names)
    atexit.register(cleanup_stale_shm, shm_names)

    # Передаём в ProcessManager
    launcher = SystemLauncher(
        stop_timeout=10,
        orchestrator_class_path=PROCESS_MANAGER_APP_CLASS_PATH,
    )
    for cfg in all_configs:
        launcher.add_process(*process(cfg))

    print(BLUEPRINT.describe())
    print(f"+ gui (классический)")
    launcher.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
