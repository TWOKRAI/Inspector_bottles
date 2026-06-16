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


def _hoist_inspector_from_metadata(processes: list) -> None:
    """Поднять ``inspector`` из ``metadata`` в прямой ключ процесса.

    GUI при сохранении рецепта кладёт ``inspector`` под ``metadata`` (домен-entity
    ``Process`` не имеет поля ``inspector`` → ``_fold_extra_into_metadata`` сворачивает
    туда). Но бэкенд читает ``ProcessConfig.inspector`` (прямой ключ, см.
    ``generic_process.py::_build_inspector``). Без подъёма join МОЛЧА выключается
    (mode=fanin) → multi-input узлы (overlay_draw, center_crop: frame+overlay) не
    сливают входы: линия не рисуется, триггер crop не срабатывает. Honor-им обе формы.
    """
    for proc in processes:
        if not isinstance(proc, dict):
            continue
        meta = proc.get("metadata")
        if isinstance(meta, dict) and meta.get("inspector") and not proc.get("inspector"):
            proc["inspector"] = meta["inspector"]


def unwrap_recipe(raw: dict) -> dict:
    """Свести GUI-рецепт (editor-слой) к запускаемой топологии.

    Модель владельца: GUI лишь формирует топологию, бэкенд её запускает — и без GUI.
    Рецепт v3 держит топологию во вложенном ``blueprint:`` (processes/wires), а привязки
    дисплеев — на верхнем уровне (``display_bindings``). Сырая topology имеет
    ``processes:`` на верхнем уровне. Эта функция разворачивает рецепт в плоскую
    топологию (тот же dict-контракт, что грузит ``SystemBuilder``), оставляя сырые
    топологии без изменений (backward-compat).

    Ключи на границе (Dict-at-Boundary):
      - ``displays`` (в bp) — **привязки** (list[dict], node_id/display_id),
        секция ``blueprint.displays`` рецепта.
      - ``display_definitions`` — **определения** дисплеев (list[dict], id/name/width/...),
        top-level секция ``displays`` рецепта. Не путать с привязками.
    """
    if not (isinstance(raw, dict) and "blueprint" in raw and "processes" not in raw):
        # Сырая topology (processes на верхнем уровне) — тоже honor-им inspector в metadata.
        if isinstance(raw, dict) and isinstance(raw.get("processes"), list):
            _hoist_inspector_from_metadata(raw["processes"])
        return raw
    bp = dict(raw["blueprint"])
    if isinstance(bp.get("processes"), list):
        _hoist_inspector_from_metadata(bp["processes"])
    # display_bindings рецепта (node_id/display_id) == секция displays топологии.
    if raw.get("display_bindings") and not bp.get("displays"):
        bp["displays"] = raw["display_bindings"]
    # Определения дисплеев (top-level displays рецепта) → display_definitions на границе.
    # display_definitions — list[dict] (Dict-at-Boundary, НЕ Pydantic).
    if raw.get("displays"):
        bp["display_definitions"] = list(raw["displays"])
    return bp


def _load_raw_dict(bp_path: Path) -> dict:
    """Прочитать YAML/JSON-файл в raw dict (без unwrap).

    Полезно для извлечения top-level секций (``devices:``) до unwrap_recipe.
    """
    if not bp_path.exists():
        print(f"[launch] ОШИБКА: топология не найдена: {bp_path}", file=sys.stderr)
        sys.exit(1)
    with open(bp_path, encoding="utf-8") as f:
        if bp_path.suffix in (".yaml", ".yml"):
            return yaml.safe_load(f) or {}
        return json.load(f)


def load_topology_dict(bp_path: Path) -> dict:
    """Прочитать YAML/JSON-топологию ИЛИ рецепт в dict (с проверкой существования).

    Рецепт (вложенный ``blueprint:``) разворачивается в топологию через
    :func:`unwrap_recipe` — так бэкенд запускает и сырую topology, и GUI-рецепт.
    """
    return unwrap_recipe(_load_raw_dict(bp_path))


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
    # displays (привязки узлов к дисплеям) — такая же суммируемая секция, как wires.
    # Без этого display-боксы из pipeline-топологии терялись бы при merge, и в
    # GUI-редакторе пайплайн не имел бы Display-ноды-стока на выходе.
    merged_displays = list(base_dict.get("displays") or []) + list(pipeline_dict.get("displays") or [])
    # display_definitions (определения дисплеев) — суммируются из фундамента и pipeline.
    # Простая конкатенация; дедупликация по id — задача Task 1.2.
    merged_defs = list(base_dict.get("display_definitions") or []) + list(
        pipeline_dict.get("display_definitions") or []
    )
    # metadata (gui_positions и пр.) — pipeline переопределяет фундамент.
    merged_metadata = {**(base_dict.get("metadata") or {}), **(pipeline_dict.get("metadata") or {})}

    merged: dict[str, Any] = {
        "name": pipeline_dict.get("name", "pipeline"),
        "description": pipeline_dict.get("description", ""),
        "processes": merged_procs,
        "wires": merged_wires,
        "displays": merged_displays,
    }
    if merged_defs:
        merged["display_definitions"] = merged_defs
    if merged_metadata:
        merged["metadata"] = merged_metadata
    return merged


def _resolve_pipeline(app: "AppManifest", override: str | None) -> Path:
    """Активный pipeline: CLI-override (имя или путь) > ``app.pipeline``."""
    if not override:
        return app.pipeline
    p = Path(override)
    if p.is_absolute() or p.suffix or ("/" in override) or ("\\" in override):
        return p
    # Голое имя ('inspection_basic') — резолвим в каталоге pipeline-ов
    return app.pipeline.parent / f"{override}.yaml"


def _manifest_pipeline_value(override: str) -> str:
    """Нормализовать CLI-override к строке для записи в ``app.yaml: pipeline``.

    Голое имя рецепта → ``recipes/<name>.yaml`` (та же форма, что пишет GUI при
    активации рецепта, см. ``app.py::_persist_active_recipe``). Явный путь — как
    есть, с нормализацией разделителей (манифест резолвит относительный путь от
    своего каталога, абсолютный — как есть).
    """
    if Path(override).is_absolute() or Path(override).suffix or ("/" in override) or ("\\" in override):
        return override.replace("\\", "/")
    return f"recipes/{override}.yaml"


def persist_pipeline_choice(manifest_path: Path, override: str) -> str:
    """Записать выбранный CLI-рецепт в манифест (``app.yaml: pipeline``).

    Делает CLI-override (`run.py <recipe>`) «последним активным рецептом»: и
    бэкенд (``main`` → ``build_launcher``), и дочерний GUI-процесс
    (``frontend/app.py`` читает ``resolve_manifest_path().pipeline``) после записи
    видят ОДИН и тот же рецепт из конфига. Без этой записи override доходил только
    до бэкенда, а GUI читал старый ``app.yaml`` — рецепты расходились (маршрутизация
    дисплеев не совпадала, дисплеи пустые).

    Запись через ruamel round-trip — комментарии ``app.yaml`` сохраняются. Если
    значение уже совпадает с текущим — файл не трогаем (не дёргаем mtime/git).

    Args:
        manifest_path: путь к ``app.yaml``.
        override: CLI-аргумент (имя рецепта или путь к топологии).

    Returns:
        Строка, записанная (или уже бывшая) в ``pipeline:`` — для логов.
    """
    value = _manifest_pipeline_value(override)

    # Сравнить с текущим pipeline: не переписывать манифест зря.
    current: str | None = None
    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as f:
            current = (yaml.safe_load(f) or {}).get("pipeline")

    if current != value:
        from multiprocess_prototype.recipes.yaml_io import update_yaml_preserving

        update_yaml_preserving(manifest_path, {"pipeline": value})
    return value


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

        # Извлекаем raw для device-секции ДО unwrap (Р11 device-hub)
        raw = _load_raw_dict(bp_path)
        blueprint = unwrap_recipe(raw)

        if app.base:
            blueprint = merge_topologies(load_topology_dict(app.base), blueprint)

        # Boot-инжект recipe_devices в конфиг device_hub (Р11 device-hub)
        from multiprocess_prototype.recipes.devices_sync import (
            extract_recipe_devices,
            inject_recipe_devices,
        )

        recipe_devices = extract_recipe_devices(raw)
        if recipe_devices:
            recipe_name = raw.get("name", bp_path.stem)
            blueprint = inject_recipe_devices(blueprint, recipe_devices, recipe_name)

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
        """Собрать готовый к запуску ``SystemLauncher``.

        Сборка proc_dict делегирована ``BlueprintAssembler`` (единая дорога для
        boot и switch).  Boot-only side effects (PluginRegistry.discover,
        build_initial_state, throttle_rules, INSPECTOR_LOG_DIR env, баннер,
        SystemLauncher-конструктор, orchestrator_config) остаются здесь.
        """
        from multiprocess_framework.modules.process_module.configs import expand_observability
        from multiprocess_framework.modules.process_manager_module.launcher.system_launcher import (
            SystemLauncher,
        )
        from multiprocess_framework.modules.process_module.plugins.registry import (
            PluginRegistry,
        )
        from multiprocess_prototype.backend.state.bootstrap import build_initial_state
        from multiprocess_prototype.backend.state.manager_setup import build_throttle_rules

        from .assembly import BlueprintAssembler, BlueprintInvalid
        from .assembly.normalize import normalize_blueprint

        sys_config = self._sys_config

        # Автообнаружение плагинов: пути из sys_config.discovery.plugin_paths
        plugin_paths = [
            str(PROJECT_ROOT / p) if not Path(p).is_absolute() else p
            for p in (sys_config.discovery.plugin_paths if sys_config.discovery.auto_discover else [])
        ]
        discovered = PluginRegistry.discover(*plugin_paths)

        # Нормализация: per-category defaults из SystemConfig → plugin-конфиги.
        # normalize_blueprint используется НАПРЯМУЮ (не build_proc_dicts), чтобы
        # не нормализовать дважды — initial_state нужен нормализованный bp_dict.
        bp_dict = normalize_blueprint(self._blueprint, sys_config)

        initial_state = build_initial_state(bp_dict, sys_config.model_dump())
        throttle_rules = build_throttle_rules()

        log_dir = sys_config.system.log_dir or "logs"

        # Зафиксировать log_dir в env: дочерние процессы наследуют его (spawn), и при
        # ГОРЯЧЕЙ замене рецепта процессы, у которых cfg.log_dir пуст, резолвят его
        # через INSPECTOR_LOG_DIR (process_launch_config._resolve_log_dir) → пишут
        # в ту же папку, а не в ./logs (fallback).
        import os as _os

        _os.environ.setdefault("INSPECTOR_LOG_DIR", str(Path(log_dir).resolve()))

        # Единая секция observability → overlay поверх дефолтных managers каждого
        # процесса (Logger/Error/Stats). Фреймворк уже даёт полный набор менеджеров;
        # overlay лишь применяет пользовательские значения из system.yaml.
        obs_overlay = expand_observability(sys_config.observability.model_dump())

        # BlueprintAssembler: stateless сборщик — та же цепочка, что была инлайн
        # (validate → check → build_configs → log_dir → process → merge_managers →
        # merge_with_defaults).  Невалидный blueprint → BlueprintInvalid (не sys.exit).
        assembler = BlueprintAssembler(
            observability_dict=obs_overlay,
            log_dir=log_dir,
        )
        try:
            proc_dicts = assembler.assemble(bp_dict)
        except BlueprintInvalid as exc:
            # Сохранить ТОЧНО прежний UX: печать ошибок → sys.exit(1).
            print("[launch] ОШИБКИ валидации topology:", file=sys.stderr)
            for err in exc.errors:
                print(f"  ✗ {err}", file=sys.stderr)
            sys.exit(1)

        self._print_banner(n_processes=len(proc_dicts), n_plugins=discovered, log_dir=log_dir)

        launcher = SystemLauncher(
            stop_timeout=sys_config.system.stop_timeout,
            orchestrator_class_path=_ORCHESTRATOR_CLASS_PATH,
            orchestrator_config={
                "initial_state": initial_state,
                "state_throttle_rules": throttle_rules,
                "backend_ctl": sys_config.backend_ctl.model_dump(),
                # Путь к system.yaml для observability hot-reload watcher (P3.3).
                "observability_config_path": str(self._system_path) if self._system_path else "",
                # Дебаунс hot-swap: коалесинг повторных/наложенных кликов 3 точек входа
                # (Recipes «Загрузить», Pipeline «Запустить»/«Перезапустить») → не «тасуем»
                # процессы. Меряется от завершения предыдущей замены. 0 = выключено (тесты).
                "replace_debounce_s": 1.0,
                # SystemConfig dict для configure_topology_engine (Dict at Boundary —
                # пиклится через spawn). Планировщик использует его для нормализации
                # blueprint (per-category defaults) + observability overlay + log_dir.
                "sys_config": sys_config.model_dump(),
            },
        )
        for name, proc_dict in proc_dicts.items():
            launcher.add_process(name, proc_dict)

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
