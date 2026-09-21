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
    #: Task 5.13: override слоя L1 (сырая секция ``observability``). ``None`` —
    #: секция берётся из ``manifest.system``, и это дефолтный путь: приложению не
    #: нужно писать Python, чтобы получить наблюдаемость. Поле нужно там, где
    #: файла нет (тесты, программная сборка) либо его надо перебить.
    observability_section: Optional[dict[str, Any]] = None
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

    # Фундамент — КОРТЕЖ фрагментов, склеиваемых по порядку тем же merge, что и
    # pipeline поверх фундамента: отдельного механизма для инфраструктуры нет.
    # Порядок значим и читается сверху вниз в манифесте.
    for base_path in manifest.base:
        base = _load_yaml_or_json(base_path)
        base_bp = (nested_blueprint_data(base) or {}) if has_top_level_blueprint(base) else base
        blueprint = _merge_topologies(base_bp, blueprint)

    return blueprint


def default_state_bootstrap(blueprint: dict[str, Any]) -> dict[str, Any]:
    """Дефолтный build-time хук: blueprint dict → начальное state-дерево (ТОЛЬКО топология).

    Generic-приложение получает наблюдаемость процессов, не написав ни строки Python:
    без посева ``initial_state`` пуст → ``GenericProcessManagerApp._setup_state_store``
    не создаёт ``StateStoreManager`` → команда ``state.get_subtree`` вообще не
    зарегистрирована (диспетчер отвечает ``No handler for key 'state.get_subtree'``),
    и ``system_overview`` рапортует пустую топологию.

    Форма ветки ``processes`` — подмножество прикладной
    (``multiprocess_prototype/backend/state/bootstrap.py::_build_process_entry``):
    ``{"config": {"plugins", "chain_targets", "priority"}, "state": {"status", "pid",
    "fps", "error"}}``. Прикладные ветки (``system``/``wires``/``services``/
    ``displays``/``recipes``/``plugins``) сюда НЕ переезжают: они читают реестры
    прототипа (DisplaysConfig, каталог рецептов), которых у framework нет.

    ``fps``/``pid``/``error`` сеются ``None``, а не нулём: ``None`` во всей системе
    означает «показания нет», а ноль — измеренный ноль. Ровно эта разница уже стоила
    прототипу семи ложных аномалий ``fps_zero_while_running`` (см. комментарий в
    прикладном ``_build_process_entry``).

    ``status`` сеется ``"stopped"``, хотя потребитель ждёт ``running``: статус
    обновляет сам ``ProcessManager`` после спавна — посев лишь создаёт лист.

    Пустой blueprint (нет процессов) → ``{"processes": {}}``, а НЕ ``{}``. Непустой
    dict проходит гейт ``_setup_state_store`` (``if not initial_state and not
    throttle_rules``), значит store создаётся всегда и команда ``state.get_subtree``
    отвечает «поддерево пусто» вместо отказа «обработчика нет». Это разные диагнозы:
    приложение без процессов — законная конфигурация, а «нет обработчика» читается
    как поломка. Решение пришпилено
    ``tests/test_state_bootstrap_hazards.py::test_empty_blueprint_decision_is_pinned``.

    Только plain dict/list/str/int/None: результат едет в дочерние процессы через
    ``spawn`` (``_pickle_sanity`` стоит на дороге в ``_build_generic``).
    """
    processes: dict[str, Any] = {}
    for proc in blueprint.get("processes") or []:
        if not isinstance(proc, dict):
            continue
        name = proc.get("process_name") or ""
        if not name:
            # Запись без имени адресовать нечем — ключ дерева был бы пустой строкой.
            continue
        processes[name] = {
            "config": {
                "plugins": list(proc.get("plugins") or []),
                "chain_targets": list(proc.get("chain_targets") or []),
                # `or "normal"`, а не `get(..., "normal")`: YAML-редактор пишет
                # явный `priority:` пустым скаляром → None (та же идиома, что у
                # прикладного бутстрапа).
                "priority": proc.get("priority") or "normal",
            },
            "state": {
                "status": "stopped",
                "pid": None,
                "fps": None,
                "error": None,
            },
        }
    return {"processes": processes}


def assemble_proc_dicts(
    blueprint: dict[str, Any],
    *,
    observability_section: dict[str, Any] | None = None,
    log_dir: str | None = None,
    app_config_path: str = "",
    recipe_path: str = "",
    telemetry_section: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Universal-шов сборки: blueprint dict → ``{name: proc_dict}`` (E3/5.3, framework-only).

    Та же цепочка, что у прикладного ``BlueprintAssembler``, но БЕЗ app-специфики
    (per-category defaults применяются снаружи, если нужны):
    validate → infer_missing_collectors → check → build_configs → log_dir →
    process → merge_managers → merge_with_defaults.

    ``observability_section`` — СЫРАЯ секция слоя L1 (Task 5.12); слой L2 читается
    из самого blueprint (``blueprint.observability``) и мержится поверх per-process.
    Раскладка (``expand_observability``) делается здесь, а не снаружи: разложенный
    снаружи L1 материализовал бы дефолты и стал бы неперебиваемым. Эта ветка —
    generic-двойник прикладного ассемблера, и без слоёв здесь секция рецепта
    молча не применялась бы ровно на тех приложениях, у которых своего
    ассемблера нет.

    ``log_dir`` **не имеет материализованного дефолта** (задача 3.3). Раньше здесь
    стояло ``= "logs"``, и эта строка попадала в конфиг КАЖДОГО процесса — то есть
    ровно тот дефект, о котором предупреждает абзац выше про ``expand_observability``:
    материализованный дефолт становится неперебиваемым. Следствие было измеримым:
    ``_resolve_log_dir`` смотрит на ``MULTIPROCESS_LOG_DIR``/``INSPECTOR_LOG_DIR``
    только когда каталог НЕ задан, поэтому воля вызывающего проигрывала нашему
    дефолту — ``examples/minimal_app`` писал в ``<репозиторий>/logs/`` даже когда
    тест явно выставлял env (111 354 байта за прогон). Задать каталог иначе было
    нечем: ни ``build_app``, ни ``app.yaml``, ни ``AppSpec`` такого поля не имеют.

    ``None`` → поле остаётся пустым, и каталог выбирает тот, кто ниже: env, а при его
    молчании — системный temp (``log_paths.default_log_base_directory``). Явное
    значение работает как прежде.

    ``telemetry_section`` (Task 1.5 плана line-sim) — глобальный дефолт секции
    ``telemetry.publish``: carve-out ``BlueprintAssembler._resolve_telemetry``
    прототипа. Без него publisher-гейт (``ProcessHeartbeat``) у generic-приложения
    не строился вовсе — зонд приёмки видел ``gate_active=False``. Per-process
    override (``processes[].telemetry``) мержится поверх глубоко; сырой override
    кладётся отдельно в ``telemetry_override`` (его читает ``config.reload``).
    Не задано нигде → ключа ``telemetry`` нет; явный ``{}`` — «включить с
    дефолтами», в «не задано» не схлопывается.

    Raises:
        BlueprintError: ``SystemBlueprint.check`` вернул ошибки.
    """
    from multiprocess_framework.modules.data_schema_module import deep_merge, process
    from multiprocess_framework.modules.data_schema_module.core.helpers import merge_with_defaults
    from multiprocess_framework.modules.process_manager_module.launcher.schema import (
        DEFAULT_PROCESS_SCHEMA,
    )
    from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
        SystemBlueprint,
    )
    from multiprocess_framework.modules.process_module.configs.observability_layers import (
        APP_CONFIG_KEY,
        OVERRIDE_CONFIG_KEY,
        RECIPE_PATH_CONFIG_KEY,
        ObservabilityLayers,
        apply_layers_to_proc_dict,
        resolve_recipe_section,
    )

    app_layer = observability_section or {}
    topology = SystemBlueprint.model_validate(blueprint)
    telemetry_overrides = {p.process_name: p.telemetry for p in topology.processes if p.telemetry is not None}
    topology.infer_missing_collectors()

    errors = topology.check()
    if errors:
        raise BlueprintError(errors)

    configs = topology.build_configs()
    for cfg in configs:
        if not cfg.log_dir and log_dir:
            cfg.log_dir = log_dir

    result: dict[str, dict[str, Any]] = {}
    for cfg in configs:
        name, proc_dict = process(cfg)
        obs_override = resolve_recipe_section(topology.observability, name)
        layers = ObservabilityLayers(app=app_layer, recipe=obs_override)
        # Раскладка «слои → менеджеры» общая с прикладным ассемблером (ревью 5.13):
        # молчание слоёв не создаёт секцию и не затирает уровень, пришедший другим
        # путём (MULTIPROCESS_LOG_LEVEL через managers_from_log_dir).
        apply_layers_to_proc_dict(proc_dict, layers)
        if obs_override:
            proc_dict["config"][OVERRIDE_CONFIG_KEY] = obs_override
        if app_layer:
            proc_dict["config"][APP_CONFIG_KEY] = dict(app_layer)
        # Task 5.13: адреса слоёв — паритет с прикладным ассемблером. Без них у
        # generic-дороги мертвы provenance-source («откуда этот ключ») и
        # observability.persist («куда сохранять») — команда отвечала бы отказом
        # «путь к рецепту неизвестен» на живой системе.
        if app_config_path:
            proc_dict["config"]["observability_config_path"] = str(app_config_path)
        if recipe_path:
            proc_dict["config"][RECIPE_PATH_CONFIG_KEY] = str(recipe_path)
        override = telemetry_overrides.get(name)
        if telemetry_section is not None or override is not None:
            proc_dict["config"]["telemetry"] = {"publish": deep_merge(telemetry_section or {}, override or {})}
        if override is not None:
            proc_dict["config"]["telemetry_override"] = override
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

        # Task 5.13 / решение владельца Р2: слой L1 generic-дороги приезжает из
        # МАНИФЕСТА. Ключ `system:` там уже был (`AppManifest.system`), но читал
        # его только баннер — из-за чего ни дети, ни оркестратор на этой дороге
        # не получали ни L1, ни адресов слоёв: `builder(blueprint)` звался одним
        # аргументом. Приложение-конфиг получает наблюдаемость, не написав ни
        # строки Python; `AppSpec.observability_section` — override для DI и тестов.
        obs_section, obs_source = self._resolve_app_observability(manifest, spec)
        recipe_path = str(manifest.pipeline) if manifest.pipeline else ""

        # Task 1.5: гейт телеметрии из того же system.yaml. Передаётся только
        # заданным — билдер приложения, написанный до 1.5, остаётся совместим.
        telemetry_kw: dict[str, Any] = {}
        telemetry_section = self._resolve_app_telemetry(manifest)
        if telemetry_section is not None:
            telemetry_kw["telemetry_section"] = telemetry_section

        builder: ProcDictsBuilder = spec.proc_dicts_builder or assemble_proc_dicts
        proc_dicts = builder(
            blueprint,
            observability_section=obs_section,
            app_config_path=obs_source,
            recipe_path=recipe_path,
            **telemetry_kw,
        )
        _pickle_sanity(proc_dicts, hook_name="proc_dicts_builder")

        # Build-time хуки: результат (dict) уйдёт в orchestrator_config → пиклится
        # через spawn → потребляется GenericProcessManagerApp child-side.
        # Ф1 Task 1.0: дефолт — топологический посев (:func:`default_state_bootstrap`),
        # а не пустой dict. Явный хук приложения выигрывает у дефолта целиком (не
        # мержится): приложение, заявившее своё дерево, получает ровно своё.
        bootstrap: StateBootstrap = spec.state_bootstrap or default_state_bootstrap
        initial_state: dict[str, Any] = bootstrap(blueprint)
        _pickle_sanity(initial_state, hook_name="state_bootstrap")

        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            orchestrator_observability_config,
        )

        orchestrator_config: dict[str, Any] = {"initial_state": initial_state}
        # Task 5.13: тот же шов, что на прикладной дороге. Оркестратор — адресат
        # слоёв, а не исключение из них; раскладка одна на обе дороги.
        orchestrator_config.update(
            orchestrator_observability_config(
                app_section=obs_section,
                recipe_section=blueprint.get("observability"),
                app_config_path=obs_source,
                recipe_path=recipe_path,
            )
        )
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

    @staticmethod
    def _resolve_app_observability(manifest: "AppManifest", spec: "AppSpec") -> tuple[dict[str, Any], str]:
        """Слой L1 generic-дороги и его адрес (Task 5.13, решение владельца Р2).

        Порядок: ``AppSpec.observability_section`` (override) → секция
        ``observability`` файла ``manifest.system`` → пусто.

        Адрес возвращается ТОЛЬКО когда секция реально пришла из файла. У
        override'а файла нет, и назвать им ``manifest.system`` значило бы соврать
        в ``provenance``: оператор пошёл бы править файл, который ни на что не
        влияет.

        Нечитаемый ``system.yaml`` роняет сборку, и это намеренно: приложение
        назвало файл в манифесте — значит рассчитывает на него. Молчаливый
        пустой L1 здесь дал бы процессы на голых дефолтах без единого признака,
        что что-то пошло не так.

        Returns:
            ``(секция, адрес)``; секция — сырой dict (возможно пустой).
        """
        if spec.observability_section is not None:
            return dict(spec.observability_section), ""
        if manifest.system is None:
            return {}, ""
        raw = _load_yaml_or_json(manifest.system)
        section = raw.get("observability") if isinstance(raw, dict) else None
        return (dict(section) if isinstance(section, dict) else {}), str(manifest.system)

    @staticmethod
    def _resolve_app_telemetry(manifest: "AppManifest") -> dict[str, Any] | None:
        """Секция ``telemetry.publish`` файла ``manifest.system`` (Task 1.5) или ``None``.

        ``None`` — секции нет: гейт не строится, все метрики публикуются каждый
        тик (поведение до 1.5). Нечитаемый файл роняет сборку — та же политика,
        что у :meth:`_resolve_app_observability`.

        Невалидная секция тоже роняет сборку (ревью 1.5): иначе процесс молча
        выключал бы гейт с одной DEBUG-строкой, а прототип на том же файле падает
        при загрузке ``SystemConfig``. Отдаётся сырой dict, не ``model_dump``:
        дефолты не материализуются и per-process override мержится поверх дельты.
        """
        if manifest.system is None:
            return None
        raw = _load_yaml_or_json(manifest.system)
        telemetry = raw.get("telemetry") if isinstance(raw, dict) else None
        publish = telemetry.get("publish") if isinstance(telemetry, dict) else None
        if publish is None:
            return None  # не-dict (``publish: fast``) идёт в валидацию и роняет сборку
        from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (
            TelemetryPublishConfig,
        )

        TelemetryPublishConfig.from_dict(publish)  # ValidationError → сборка падает
        return dict(publish)

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
    # nosec B403 — только `dumps` собственного результата хука: проверка
    # пиклябельности перед spawn, десериализации чужих данных здесь нет.
    import pickle  # nosec B403

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
