"""Сборка системы из главного конфига: фундамент ⊕ pipeline → SystemLauncher.

``SystemBuilder`` — app-слой: знает про манифест (app.yaml), оркестратор прототипа
и state bootstrap. Точка входа (``main.py``) остаётся тонкой и лишь вызывает билдер.

Заметка на будущее: универсальную часть (blueprint dict → SystemLauncher) можно
позже вынести во framework (``process_manager_module/launcher``), когда дойдём до
фазы извлечения общих частей. Прототип-специфика (манифест, orchestrator_class_path,
state bootstrap) останется здесь.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from multiprocess_framework.modules.process_manager_module.launcher.system_launcher import (
        SystemLauncher,
    )

    from .config.manifest import AppManifest
    from .config.schemas import SystemConfig

# Корень проекта (Inspector_bottles) — для резолва путей плагинов.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

_ORCHESTRATOR_CLASS_PATH = "multiprocess_prototype.orchestrator.ProcessManagerProcessApp"


# ---------------------------------------------------------------------------
# Чистые помощники работы с топологиями
# ---------------------------------------------------------------------------


def load_topology_dict(bp_path: Path) -> dict:
    """Прочитать YAML/JSON-топологию в dict (с проверкой существования)."""
    if not bp_path.exists():
        print(f"[launch] ОШИБКА: топология не найдена: {bp_path}", file=sys.stderr)
        sys.exit(1)
    with open(bp_path, encoding="utf-8") as f:
        if bp_path.suffix in (".yaml", ".yml"):
            return yaml.safe_load(f)
        return json.load(f)


def merge_topologies(base_dict: dict, pipeline_dict: dict) -> dict:
    """Суммировать фундамент и pipeline в одну топологию.

    Фундамент (``base``) даёт always-on процессы (презентация и пр.), ``pipeline`` —
    полезную нагрузку. При коллизии имён процессов побеждает фундамент
    (дубль из pipeline отбрасывается с предупреждением). Pipeline задаёт
    ``name``/``description`` результата. Pipeline адресует процессы фундамента
    по имени (``chain_targets``), поэтому отдельные wires к ним не нужны.
    """
    base_procs = list(base_dict.get("processes") or [])
    base_names = {p.get("process_name") for p in base_procs}

    merged_procs = list(base_procs)
    for proc in pipeline_dict.get("processes") or []:
        if proc.get("process_name") in base_names:
            print(
                f"[launch] процесс '{proc.get('process_name')}' уже есть в фундаменте — дубль из pipeline пропущен",
                file=sys.stderr,
            )
            continue
        merged_procs.append(proc)

    merged_wires = list(base_dict.get("wires") or []) + list(pipeline_dict.get("wires") or [])

    return {
        "name": pipeline_dict.get("name", "pipeline"),
        "description": pipeline_dict.get("description", ""),
        "processes": merged_procs,
        "wires": merged_wires,
    }


def _merge_defaults(bp_dict: dict, defaults: "SystemConfig") -> dict:
    """Merge defaults из system.yaml в plugin-конфиги topology.

    Для каждого плагина: defaults[category] | plugin_inline_config.
    Inline-значения имеют приоритет (override).
    """
    for proc in bp_dict.get("processes", []):
        for plugin in proc.get("plugins", []):
            category = plugin.get("category", "")
            category_defaults = defaults.defaults_for_category(category)
            if category_defaults:
                merged = {**category_defaults, **plugin}
                plugin.clear()
                plugin.update(merged)
    return bp_dict


def _resolve_pipeline(app: "AppManifest", override: str | None) -> Path:
    """Активный pipeline: CLI-override (имя или путь) > ``app.pipeline``."""
    if not override:
        return app.pipeline
    p = Path(override)
    if p.is_absolute() or p.suffix or ("/" in override) or ("\\" in override):
        return p
    # Голое имя ('inspection_basic') — резолвим в каталоге pipeline-ов
    return app.pipeline.parent / f"{override}.yaml"


# ---------------------------------------------------------------------------
# SystemBuilder — сборка SystemLauncher
# ---------------------------------------------------------------------------


class SystemBuilder:
    """Собирает ``SystemLauncher`` из system-конфига и dict-топологии.

    Состояние резолвится фабриками (``from_manifest`` / ``from_topology_path``)
    и хранится в полях — ``build()`` не требует параметров.
    """

    def __init__(
        self,
        *,
        sys_config: "SystemConfig",
        blueprint: dict,
        topology_path: Path,
        manifest_path: Path | None = None,
        system_path: Path | None = None,
        theme: str | None = None,
    ) -> None:
        self._sys_config = sys_config
        self._blueprint = blueprint
        self._topology_path = topology_path
        self._manifest_path = manifest_path
        self._system_path = system_path
        self._theme = theme

    # --- Фабрики ---

    @classmethod
    def from_manifest(cls, app: "AppManifest", pipeline_override: str | None = None) -> "SystemBuilder":
        """Из главного конфига: system.yaml + (фундамент ⊕ активный pipeline)."""
        from .config.schemas import load_system_config

        sys_config = load_system_config(app.system)
        bp_path = _resolve_pipeline(app, pipeline_override)
        blueprint = load_topology_dict(bp_path)
        if app.base:
            blueprint = merge_topologies(load_topology_dict(app.base), blueprint)
        return cls(
            sys_config=sys_config,
            blueprint=blueprint,
            topology_path=bp_path,
            manifest_path=app.source,
            system_path=app.system,
            theme=app.styles.active,
        )

    @classmethod
    def from_topology_path(cls, system_path: Path, topology_path: Path) -> "SystemBuilder":
        """LEGACY: из явного system.yaml + topology (без манифеста/фундамента)."""
        from .config.schemas import load_system_config

        return cls(
            sys_config=load_system_config(system_path),
            blueprint=load_topology_dict(topology_path),
            topology_path=topology_path,
            system_path=system_path,
        )

    # --- Сборка ---

    def build(self) -> "SystemLauncher":
        """Собрать готовый к запуску ``SystemLauncher``."""
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

        sys_config = self._sys_config

        # Автообнаружение плагинов: пути из sys_config.discovery.plugin_paths
        plugin_paths = [
            str(PROJECT_ROOT / p) if not Path(p).is_absolute() else p
            for p in (sys_config.discovery.plugin_paths if sys_config.discovery.auto_discover else [])
        ]
        discovered = PluginRegistry.discover(*plugin_paths)

        bp_dict = _merge_defaults(self._blueprint, sys_config)

        initial_state = build_initial_state(bp_dict, sys_config.model_dump())
        throttle_rules = build_throttle_rules()

        topology = SystemBlueprint.model_validate(bp_dict)
        errors = topology.check()
        if errors:
            print("[launch] ОШИБКИ валидации topology:", file=sys.stderr)
            for err in errors:
                print(f"  ✗ {err}", file=sys.stderr)
            sys.exit(1)

        configs = topology.build_configs()
        log_dir = sys_config.system.log_dir or "logs"
        for cfg in configs:
            if not cfg.log_dir:
                cfg.log_dir = log_dir

        self._print_banner(n_processes=len(configs), n_plugins=discovered, log_dir=log_dir)

        launcher = SystemLauncher(
            stop_timeout=sys_config.system.stop_timeout,
            orchestrator_class_path=_ORCHESTRATOR_CLASS_PATH,
            orchestrator_config={
                "initial_state": initial_state,
                "state_throttle_rules": throttle_rules,
            },
        )
        for cfg in configs:
            launcher.add_process(*process(cfg))

        return launcher

    def _print_banner(self, *, n_processes: int, n_plugins: Any, log_dir: str) -> None:
        """Единый startup-баннер: какие файлы реально подхвачены."""
        bar = "=" * 54
        lines = [bar, " Inspector Bottles", bar]
        if self._manifest_path is not None:
            lines.append(f" manifest : {self._manifest_path}")
        if self._system_path is not None:
            lines.append(f" system   : {self._system_path.name}")
        lines.append(f" pipeline : {self._topology_path.name}")
        if self._theme is not None:
            lines.append(f" theme    : {self._theme}")
        lines.append(f" plugins  : {n_plugins}")
        lines.append(f" log_dir  : {Path(log_dir).resolve()}")
        lines.append(f" processes: {n_processes}")
        lines.append(bar)
        print("\n".join(lines))
