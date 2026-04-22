"""Inspector Prototype v3 — entry point.

Phase 3: поддержка N гетерогенных камер из settings profile / рецепта.
"""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent  # Inspector_prototype
_modules = _root / "multiprocess_framework" / "modules"
for _p in (_root, _modules):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load_cameras_from_profile():
    """Загрузить список камер из активного settings profile."""
    from multiprocess_prototype_v3.config.app import build_cameras_from_profile
    from multiprocess_prototype_v3.frontend.managers.settings_yaml_store import SettingsYamlStore

    store = SettingsYamlStore()
    data = store.read_dict() or {}
    current_id = data.get("current_profile", "default")
    profiles = data.get("profiles", {})
    profile = profiles.get(current_id, {})

    return build_cameras_from_profile(
        camera_count=profile.get("camera_count", 1),
        camera_source_type=profile.get("camera_source_type", "simulator"),
        ring_buffer_size=profile.get("ring_buffer_size", 3),
    )


def main() -> int:
    from multiprocess_framework.modules.data_schema_module import process
    from multiprocess_framework.modules.process_manager_module import SystemLauncher

    from multiprocess_prototype_v3.config import AppConfig

    cameras = _load_cameras_from_profile()
    app = AppConfig(cameras=cameras)
    launcher = SystemLauncher(stop_timeout=app.stop_timeout)
    for cfg in app.all_process_configs():
        launcher.add_process(*process(cfg))
    launcher.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
