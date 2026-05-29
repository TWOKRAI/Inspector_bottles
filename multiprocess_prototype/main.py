"""multiprocess_prototype — точка входа приложения.

Запуск управляется главным конфигом (манифестом) ``app.yaml``::

    main() → load_manifest(app.yaml) → build_launcher(app) → SystemLauncher.run()

``build_launcher`` собирает систему из:
  1. ``system.yaml`` (defaults) — путь из манифеста;
  2. автообнаружения плагинов;
  3. активного pipeline (runnable-топология) — путь из манифеста;
  4. (Фаза 2) фундамент-топологии ``base.yaml``, суммируемой с pipeline.

``bootstrap(topology_path)`` — legacy-обёртка для тестов и README фреймворка
(собирает систему из явного пути топологии + ``CONFIG_PATH``). Новый код
использует ``build_launcher(load_manifest(...))``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from multiprocess_framework.modules.process_manager_module.launcher.system_launcher import (
        SystemLauncher,
    )
    from multiprocess_prototype.backend.config.manifest import AppManifest
    from multiprocess_prototype.backend.config.schemas import SystemConfig

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent

# Корень проекта в sys.path для импортов фреймворка и prototype
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CONFIG_PATH = HERE / "backend" / "config" / "system.yaml"
DEFAULT_MANIFEST = HERE / "app.yaml"
# Дефолтный pipeline для legacy bootstrap() и тестов. Основной выбор — через app.yaml.
DEFAULT_BLUEPRINT = HERE / "backend" / "topology" / "region_pipeline.yaml"


def _merge_defaults(bp_dict: dict, defaults: "SystemConfig") -> dict:
    """Merge defaults из system.yaml в plugin-конфиги topology.

    Для каждого плагина: defaults[category] | plugin_inline_config.
    Inline-значения имеют приоритет (override).
    """

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


def _load_topology_dict(bp_path: Path) -> dict:
    """Прочитать YAML/JSON-топологию в dict (с проверкой существования)."""
    if not bp_path.exists():
        print(f"[launch] ОШИБКА: топология не найдена: {bp_path}", file=sys.stderr)
        sys.exit(1)
    with open(bp_path, encoding="utf-8") as f:
        if bp_path.suffix in (".yaml", ".yml"):
            return yaml.safe_load(f)
        return json.load(f)


def _print_banner(
    *,
    topology_path: Path,
    log_dir: str,
    n_processes: int,
    n_plugins: object,
    manifest_path: Path | None = None,
    system_path: Path | None = None,
    theme: str | None = None,
) -> None:
    """Единый startup-баннер: какие файлы реально подхвачены."""
    bar = "=" * 54
    lines = [bar, " Inspector Bottles", bar]
    if manifest_path is not None:
        lines.append(f" manifest : {manifest_path}")
    if system_path is not None:
        lines.append(f" system   : {system_path.name}")
    lines.append(f" pipeline : {topology_path.name}")
    if theme is not None:
        lines.append(f" theme    : {theme}")
    lines.append(f" plugins  : {n_plugins}")
    lines.append(f" log_dir  : {Path(log_dir).resolve()}")
    lines.append(f" processes: {n_processes}")
    lines.append(bar)
    print("\n".join(lines))


def _assemble_launcher(
    sys_config: "SystemConfig",
    bp_dict: dict,
    *,
    topology_path: Path,
    manifest_path: Path | None = None,
    system_path: Path | None = None,
    theme: str | None = None,
) -> "SystemLauncher":
    """Общая сборка ``SystemLauncher`` из system-конфига и dict-топологии."""
    from multiprocess_framework.modules.data_schema_module import process
    from multiprocess_framework.modules.process_manager_module.launcher.system_launcher import (
        SystemLauncher,
    )
    from multiprocess_framework.modules.process_module.generic.blueprint import (
        SystemBlueprint,
    )
    from multiprocess_framework.modules.process_module.plugins.registry import (
        PluginRegistry,
    )
    from multiprocess_prototype.backend.state.bootstrap import build_initial_state
    from multiprocess_prototype.backend.state.manager_setup import build_throttle_rules

    # Автообнаружение плагинов: пути из sys_config.discovery.plugin_paths
    _plugin_paths = [
        str(PROJECT_ROOT / p) if not Path(p).is_absolute() else p
        for p in (sys_config.discovery.plugin_paths if sys_config.discovery.auto_discover else [])
    ]
    discovered = PluginRegistry.discover(*_plugin_paths)

    # Merge defaults → topology plugin configs
    bp_dict = _merge_defaults(bp_dict, sys_config)

    # State bootstrap — построение начального дерева состояния
    initial_state = build_initial_state(bp_dict, sys_config.model_dump())
    throttle_rules = build_throttle_rules()

    topology = SystemBlueprint.model_validate(bp_dict)

    # Валидация
    errors = topology.check()
    if errors:
        print("[launch] ОШИБКИ валидации topology:", file=sys.stderr)
        for err in errors:
            print(f"  ✗ {err}", file=sys.stderr)
        sys.exit(1)

    # Сборка конфигов + прокинуть log_dir из system.yaml
    configs = topology.build_configs()
    log_dir = sys_config.system.log_dir or "logs"
    for cfg in configs:
        if not cfg.log_dir:
            cfg.log_dir = log_dir

    _print_banner(
        topology_path=topology_path,
        log_dir=log_dir,
        n_processes=len(configs),
        n_plugins=discovered,
        manifest_path=manifest_path,
        system_path=system_path,
        theme=theme,
    )

    launcher = SystemLauncher(
        stop_timeout=sys_config.system.stop_timeout,
        orchestrator_class_path=("multiprocess_prototype.orchestrator.ProcessManagerProcessApp"),
        orchestrator_config={
            "initial_state": initial_state,
            "state_throttle_rules": throttle_rules,
        },
    )
    for cfg in configs:
        launcher.add_process(*process(cfg))

    return launcher


def _resolve_pipeline(app: "AppManifest", override: str | None) -> Path:
    """Активный pipeline: CLI-override (имя или путь) > app.pipeline."""
    if not override:
        return app.pipeline
    p = Path(override)
    if p.is_absolute() or p.suffix or ("/" in override) or ("\\" in override):
        return p
    # Голое имя ('inspection_basic') — резолвим в каталоге pipeline-ов
    return app.pipeline.parent / f"{override}.yaml"


def build_launcher(app: "AppManifest", pipeline_override: str | None = None) -> "SystemLauncher":
    """Собрать систему из главного конфига (манифеста).

    Args:
        app: Загруженный ``AppManifest`` (см. ``load_manifest``).
        pipeline_override: Необязательное переопределение активного pipeline
            (имя из каталога топологий или путь). Приоритет выше ``app.pipeline``.

    Returns:
        Готовый к запуску ``SystemLauncher``.
    """
    from multiprocess_prototype.backend.config.schemas import load_system_config

    sys_config = load_system_config(app.system)
    bp_path = _resolve_pipeline(app, pipeline_override)
    bp_dict = _load_topology_dict(bp_path)
    # Фаза 2: if app.base: bp_dict = merge(_load_topology_dict(app.base), bp_dict)

    return _assemble_launcher(
        sys_config,
        bp_dict,
        topology_path=bp_path,
        manifest_path=app.source,
        system_path=app.system,
        theme=app.styles.active,
    )


def bootstrap(topology_path: Path | str | None = None) -> "SystemLauncher":
    """LEGACY: собрать систему из явного пути топологии + ``CONFIG_PATH``.

    Сохранено для тестов и README фреймворка. Новый код — ``build_launcher``.
    """
    from multiprocess_prototype.backend.config.schemas import load_system_config

    sys_config = load_system_config(CONFIG_PATH)
    bp_path = Path(topology_path) if topology_path else DEFAULT_BLUEPRINT
    bp_dict = _load_topology_dict(bp_path)
    return _assemble_launcher(sys_config, bp_dict, topology_path=bp_path, system_path=CONFIG_PATH)


def resolve_manifest_path() -> Path:
    """Путь к главному конфигу: env ``INSPECTOR_MANIFEST`` > ``app.yaml`` рядом с модулем.

    Общий источник для backend (``main``) и GUI-процесса (``app.py``), чтобы
    оба читали один и тот же манифест.
    """
    return Path(os.environ.get("INSPECTOR_MANIFEST") or DEFAULT_MANIFEST)


def main(pipeline_override: str | None = None) -> int:
    """Запуск приложения: главный конфиг → сборка → run."""
    from multiprocess_prototype.backend.config.manifest import load_manifest

    app = load_manifest(resolve_manifest_path())
    build_launcher(app, pipeline_override).run()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
