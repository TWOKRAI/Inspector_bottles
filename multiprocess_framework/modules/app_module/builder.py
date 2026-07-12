"""``SystemBuilder`` + ``AppSpec`` — generic composition root (Ф5.11).

Собирает ``SystemLauncher`` из ``app.yaml`` под одной крышей (шов E3/5.3):
env-алиасы → манифест (через :class:`ManifestStore`) → авто-скан плагинов+сервисов
(``discover``) → blueprint → proc_dicts → баннер из ``manifest.name`` →
``assemble_launcher`` с DI-оркестратором.

Два режима (см. :class:`AppSpec`):
  - **generic** (minimal_app / дефолт) — granular build-time хуки с framework-defaults:
    :func:`default_blueprint_loader` + :func:`assemble_proc_dicts`, оркестратор — базовый
    ``ProcessManagerProcess``. Так «рыба» доказывает самодостаточность без прототипа.
  - **factory** (прототип) — ``launcher_factory`` собирает launcher сам (его
    сложившийся ``build()`` — источник истины, снапшот 5.1 не трогаем); ``run_app``
    оборачивает его generic-контуром (env-алиасы, банер). Вход прототипа постепенно
    выражается через ``run_app``, back-compat полный.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .env import apply_env_aliases
from .interfaces import (
    BlueprintLoader,
    LauncherFactory,
    ProcDictsBuilder,
    StateBootstrap,
    ThrottleRules,
)

#: Дефолтный оркестратор generic-пути (minimal_app). Резолвится child-side по
#: строке (Dict-at-Boundary) — статического импорта framework→app_module нет.
GENERIC_ORCHESTRATOR_CLASS_PATH = "multiprocess_framework.modules.app_module.orchestrator.GenericProcessManagerApp"

if TYPE_CHECKING:
    from multiprocess_framework.modules.process_manager_module.launcher.system_launcher import (
        SystemLauncher,
    )

    from .manifest import AppManifest


class BlueprintError(Exception):
    """Blueprint не прошёл валидацию (``SystemBlueprint.check``). ``errors`` — список причин."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"Blueprint validation failed: {errors}")


@dataclass(frozen=True)
class AppSpec:
    """Декларация приложения для ``run_app`` — DI-контейнер (не hook-фреймворк).

    Двухсортные хук-точки (Ф5.12):
      - **build-time** callable (до spawn): ``blueprint_loader`` / ``proc_dicts_builder``
        / ``state_bootstrap`` / ``throttle_rules`` — результат пиклится в конфиг;
      - **runtime** (после spawn): ``orchestrator_class_path`` (import-path строка) +
        ``orchestrator_config`` (dict) — подкласс резолвится child-side.

    Правило против hook-взрыва (ADR-APP-006): хук здесь появляется, только если
    прототип нуждается в нём сегодня И minimal_app бутится без него (опционален).
    """

    manifest_path: Path
    pipeline_override: Optional[str] = None
    #: Escape-hatch: приложение собирает launcher само (прототип). Приоритетен.
    launcher_factory: Optional[LauncherFactory] = None
    #: Granular build-time хуки (generic путь). None → framework-default.
    blueprint_loader: Optional[BlueprintLoader] = None
    proc_dicts_builder: Optional[ProcDictsBuilder] = None
    state_bootstrap: Optional[StateBootstrap] = None
    throttle_rules: Optional[ThrottleRules] = None
    #: Runtime-хук: DI оркестратора. None → generic ``GenericProcessManagerApp``.
    orchestrator_class_path: Optional[str] = None
    orchestrator_config: dict[str, Any] = field(default_factory=dict)
    stop_timeout: float = 5.0


# ---------------------------------------------------------------------------
# Generic build-time defaults (framework-символы; app-специфики нет)
# ---------------------------------------------------------------------------


def default_blueprint_loader(manifest: "AppManifest") -> dict[str, Any]:
    """Дефолтный build-time хук: манифест → blueprint dict (base ⊕ pipeline).

    Читает ``manifest.pipeline`` (YAML/JSON), разворачивает рецепт v3
    (``blueprint:`` → плоская топология через ``recipe.nested_blueprint_data``),
    суммирует с ``manifest.base`` если задан. Generic: без per-recipe-специфики.
    """
    from multiprocess_framework.modules.recipe import has_top_level_blueprint, nested_blueprint_data

    pipeline = _load_yaml_or_json(manifest.pipeline)
    blueprint = (nested_blueprint_data(pipeline) or {}) if has_top_level_blueprint(pipeline) else pipeline

    if manifest.base is not None:
        base = _load_yaml_or_json(manifest.base)
        base_bp = (nested_blueprint_data(base) or {}) if has_top_level_blueprint(base) else base
        blueprint = _merge_topologies(base_bp, blueprint)

    return blueprint


def assemble_proc_dicts(
    blueprint: dict[str, Any],
    *,
    observability_dict: dict[str, Any] | None = None,
    log_dir: str = "logs",
) -> dict[str, dict[str, Any]]:
    """Universal-шов сборки: blueprint dict → ``{name: proc_dict}`` (E3/5.3, framework-only).

    Та же цепочка, что у прикладного ``BlueprintAssembler``, но БЕЗ app-специфики
    (per-category defaults применяются снаружи, если нужны):
    validate → infer_missing_inspectors → check → build_configs → log_dir →
    process → merge_managers → merge_with_defaults.

    Raises:
        BlueprintError: ``SystemBlueprint.check`` вернул ошибки.
    """
    from multiprocess_framework.modules.data_schema_module import process
    from multiprocess_framework.modules.data_schema_module.core.helpers import merge_with_defaults
    from multiprocess_framework.modules.process_manager_module.launcher.schema import (
        DEFAULT_PROCESS_SCHEMA,
    )
    from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
        SystemBlueprint,
    )
    from multiprocess_framework.modules.process_module.configs.managers_config import merge_managers

    obs = observability_dict or {}
    topology = SystemBlueprint.model_validate(blueprint)
    topology.infer_missing_inspectors()

    errors = topology.check()
    if errors:
        raise BlueprintError(errors)

    configs = topology.build_configs()
    for cfg in configs:
        if not cfg.log_dir:
            cfg.log_dir = log_dir

    result: dict[str, dict[str, Any]] = {}
    for cfg in configs:
        name, proc_dict = process(cfg)
        proc_dict["managers"] = merge_managers(proc_dict.get("managers", {}), obs)
        proc_dict = merge_with_defaults(proc_dict, DEFAULT_PROCESS_SCHEMA)
        result[name] = proc_dict
    return result


# ---------------------------------------------------------------------------
# SystemBuilder — сборка launcher из AppSpec
# ---------------------------------------------------------------------------


class SystemBuilder:
    """Generic-сборщик ``SystemLauncher`` из :class:`AppSpec`.

    ``build()`` не спавнит процессы — только конструирует launcher (env-алиасы →
    манифест → discover → blueprint → proc_dicts → баннер → ``assemble_launcher``).
    """

    def __init__(self, spec: AppSpec) -> None:
        self._spec = spec

    def build(self) -> "SystemLauncher":
        """Собрать готовый к запуску (не запущенный) ``SystemLauncher``."""
        from .manifest import AppManifest  # noqa: F401 — тип для аннотаций/ясности
        from .store import ManifestStore

        apply_env_aliases()

        spec = self._spec
        manifest = ManifestStore(spec.manifest_path).load()

        if spec.launcher_factory is not None:
            # Factory-режим: приложение собирает launcher само (прототип). Generic-контур
            # ограничен env-алиасами (выше); баннер/discover — за приложением (оно уже
            # печатает свой детальный баннер). Так вход прототипа выражается через run_app
            # без дубля презентации, back-compat полный.
            return spec.launcher_factory(manifest, spec.pipeline_override)

        return self._build_generic(manifest)

    def _build_generic(self, manifest: "AppManifest") -> "SystemLauncher":
        from multiprocess_framework.modules.process_manager_module.launcher import assemble_launcher

        from .discovery import DiscoveryResult, discover

        spec = self._spec

        discovery = DiscoveryResult()
        if manifest.discovery.auto_discover:
            discovery = discover(
                plugin_paths=manifest.discovery.plugin_paths,
                service_paths=manifest.discovery.service_paths,
            )

        loader: BlueprintLoader = spec.blueprint_loader or default_blueprint_loader
        blueprint = loader(manifest)
        _pickle_sanity(blueprint, hook_name="blueprint_loader")

        builder: ProcDictsBuilder = spec.proc_dicts_builder or assemble_proc_dicts
        proc_dicts = builder(blueprint)
        _pickle_sanity(proc_dicts, hook_name="proc_dicts_builder")

        # Build-time хуки: результат (dict) уйдёт в orchestrator_config → пиклится
        # через spawn → потребляется GenericProcessManagerApp child-side.
        initial_state: dict[str, Any] = {}
        if spec.state_bootstrap is not None:
            bootstrap: StateBootstrap = spec.state_bootstrap
            initial_state = bootstrap(blueprint)
            _pickle_sanity(initial_state, hook_name="state_bootstrap")

        orchestrator_config: dict[str, Any] = {"initial_state": initial_state}
        if spec.throttle_rules is not None:
            throttle: ThrottleRules = spec.throttle_rules
            orchestrator_config["state_throttle_rules"] = throttle(blueprint)
            _pickle_sanity(orchestrator_config["state_throttle_rules"], hook_name="throttle_rules")
        # Явный orchestrator_config приложения — последним (может переопределить).
        orchestrator_config.update(spec.orchestrator_config)

        self._print_banner(
            manifest,
            n_plugins=discovery.plugins_discovered,
            n_services=len(discovery.services),
            n_processes=len(proc_dicts),
        )

        return assemble_launcher(
            proc_dicts,
            # None → generic-оркестратор «рыбы» (minimal_app бутится на нём).
            orchestrator_class_path=spec.orchestrator_class_path or GENERIC_ORCHESTRATOR_CLASS_PATH,
            orchestrator_config=orchestrator_config,
            stop_timeout=spec.stop_timeout,
        )

    def _print_banner(
        self,
        manifest: "AppManifest",
        *,
        n_plugins: Any,
        n_services: Any,
        n_processes: int,
    ) -> None:
        """Единый startup-баннер: имя приложения (A8) + что реально подхвачено."""
        bar = "=" * 54
        lines = [bar, f" {manifest.name}", bar, f" manifest : {manifest.source}"]
        if manifest.system is not None:
            lines.append(f" system   : {manifest.system.name}")
        lines.append(f" pipeline : {manifest.pipeline.name}")
        lines.append(f" plugins  : {n_plugins}")
        lines.append(f" services : {n_services}")
        lines.append(f" processes: {n_processes}")
        lines.append(bar)
        print("\n".join(lines))


# ---------------------------------------------------------------------------
# Внутренние generic-помощники
# ---------------------------------------------------------------------------


def _load_yaml_or_json(path: Path) -> dict[str, Any]:
    import json

    import yaml

    if not Path(path).exists():
        raise FileNotFoundError(f"topology/pipeline не найден: {path}")
    with open(path, encoding="utf-8") as f:
        if Path(path).suffix in (".yaml", ".yml"):
            return yaml.safe_load(f) or {}
        return json.load(f)


def _pickle_sanity(value: Any, *, hook_name: str) -> None:
    """Ранняя проверка пиклябельности результата build-time хука (косметика Ф5.12→Ф5.13).

    Build-time хуки (:class:`BlueprintLoader`/:class:`ProcDictsBuilder`/
    :class:`StateBootstrap`/:class:`ThrottleRules`) выполняются в launcher-процессе
    (родитель), а их РЕЗУЛЬТАТ уходит через ``spawn`` дочерним процессам (proc_dicts —
    напрямую, initial_state/state_throttle_rules — упакованными в ``orchestrator_config``).
    Без этой проверки непиклябельный объект (например, лямбда/локальная функция/сокет
    в значении, случайно оставленные приложением) падает ГЛУБОКО в
    ``multiprocessing.Process.start()`` с малопонятной трассировкой, не указывающей на
    виновника. Fail fast здесь называет хук по имени.

    Raises:
        TypeError: значение не проходит ``pickle.dumps`` — сообщение называет хук.
    """
    import pickle

    try:
        pickle.dumps(value)
    except Exception as exc:
        raise TypeError(
            f"build-time хук {hook_name!r} вернул непиклябельный результат (нужен для spawn дочерних процессов): {exc}"
        ) from exc


def _merge_topologies(base: dict[str, Any], pipeline: dict[str, Any]) -> dict[str, Any]:
    """Суммировать фундамент и pipeline (generic-версия): процессы+wires конкатенируются.

    При коллизии имён процессов побеждает фундамент (дубль из pipeline отбрасывается).
    Prototype-специфика (displays/display_definitions/metadata) сюда не входит — её
    merge живёт за швом в прикладном ``blueprint_loader``.
    """
    base_procs = list(base.get("processes") or [])
    base_names = {p.get("process_name") for p in base_procs}
    merged_procs = list(base_procs)
    for proc in pipeline.get("processes") or []:
        if proc.get("process_name") in base_names:
            continue
        merged_procs.append(proc)
    return {
        "name": pipeline.get("name", "pipeline"),
        "description": pipeline.get("description", ""),
        "processes": merged_procs,
        "wires": list(base.get("wires") or []) + list(pipeline.get("wires") or []),
    }
