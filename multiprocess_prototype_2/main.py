"""multiprocess_prototype_2 — точка входа приложения.

Декларативный запуск:
  1. Загрузка system.yaml (defaults)
  2. Автообнаружение плагинов
  3. Загрузка topology из JSON + merge defaults
  4. Валидация
  5. Запуск через SystemLauncher
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent

# Корень проекта в sys.path для импортов фреймворка и prototype_2
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PLUGINS_DIR = HERE / "plugins"
CONFIG_PATH = HERE / "config" / "system.yaml"
DEFAULT_BLUEPRINT = HERE / "topology" / "camera_gui.yaml"


def _merge_defaults(bp_dict: dict, defaults: "SystemConfig") -> dict:
    """Merge defaults из system.yaml в plugin-конфиги topology.

    Для каждого плагина: defaults[category] | plugin_inline_config.
    Inline-значения имеют приоритет (override).
    """
    from multiprocess_prototype_2.config.schemas import SystemConfig

    for process in bp_dict.get("processes", []):
        for plugin in process.get("plugins", []):
            category = plugin.get("category", "")
            category_defaults = defaults.defaults_for_category(category)
            if category_defaults:
                # defaults заполняют отсутствующие поля, inline имеет приоритет
                merged = {**category_defaults, **plugin}
                plugin.clear()
                plugin.update(merged)
    return bp_dict


def bootstrap(topology_path: Path | str | None = None) -> "SystemLauncher":
    """Сборка системы из system.yaml + topology JSON.

    Args:
        topology_path: путь к topology JSON (по умолчанию phase0_heartbeat.json)

    Returns:
        Готовый к запуску SystemLauncher
    """
    from multiprocess_framework.modules.data_schema_module import process
    from multiprocess_framework.modules.process_module.generic.blueprint import (
        SystemBlueprint,
    )
    from multiprocess_framework.modules.process_module.plugins.registry import (
        PluginRegistry,
    )
    from multiprocess_framework.modules.process_manager_module.launcher.system_launcher import (
        SystemLauncher,
    )
    from multiprocess_prototype_2.config.schemas import load_system_config

    # 1. Загрузка defaults
    sys_config = load_system_config(CONFIG_PATH)
    print(f"[bootstrap] config: {CONFIG_PATH.name} загружен")

    # 2. Автообнаружение плагинов
    discovered = PluginRegistry.discover(str(PLUGINS_DIR))
    print(f"[bootstrap] обнаружено плагинов: {discovered}")

    # 3. Загрузка topology из JSON
    bp_path = Path(topology_path) if topology_path else DEFAULT_BLUEPRINT
    if not bp_path.exists():
        print(f"[bootstrap] ОШИБКА: topology не найден: {bp_path}", file=sys.stderr)
        sys.exit(1)

    with open(bp_path, encoding="utf-8") as f:
        if bp_path.suffix in (".yaml", ".yml"):
            bp_dict = yaml.safe_load(f)
        else:
            bp_dict = json.load(f)

    # 4. Merge defaults → topology plugin configs
    bp_dict = _merge_defaults(bp_dict, sys_config)

    topology = SystemBlueprint.model_validate(bp_dict)
    print(f"[bootstrap] topology: {topology.name} - {topology.description}")

    # 5. Валидация
    errors = topology.check()
    if errors:
        print("[bootstrap] ОШИБКИ валидации topology:", file=sys.stderr)
        for err in errors:
            print(f"  ✗ {err}", file=sys.stderr)
        sys.exit(1)

    # 6. Сборка launcher
    configs = topology.build_configs()
    launcher = SystemLauncher(stop_timeout=sys_config.system.stop_timeout)
    for cfg in configs:
        launcher.add_process(*process(cfg))

    print(f"[bootstrap] процессов: {len(configs)}")
    return launcher


def main(topology_path: str | None = None) -> int:
    """Запуск приложения."""
    launcher = bootstrap(topology_path)
    launcher.run()
    return 0


if __name__ == "__main__":
    bp = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(main(bp))
