"""Runtime-хуки прототипного оркестратора (Ф5.12).

``ProcessManagerProcessApp`` = ``GenericProcessManagerApp`` + два runtime-хука.
Тела хуков вынесены сюда свободными функциями, чтобы сам класс-оркестратор
оставался тонкой композицией (≤ ~30 LOC): класс лишь ПОДКЛЮЧАЕТ хуки в seam'ы
generic-оркестратора, а Inspector-специфика (BlueprintAssembler, DisplayRegistry)
живёт здесь, за швом.

Оба хука — «runtime»-сорта (после spawn): они резолвятся child-side через
``orchestrator_class_path`` вместе с классом-оркестратором.

* :func:`configure_topology_engine` — seam ``_configure_runtime``: собирает
  прототипный движок горячей замены (unwrap → normalize → assemble + планировщик).
* :func:`apply_topology_with_display_reload` — override ``apply_topology``:
  переналивает DisplayRegistry вокруг generic apply.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from multiprocess_framework.modules.app_module.orchestrator import GenericProcessManagerApp


def configure_topology_engine(orchestrator: "GenericProcessManagerApp") -> None:
    """Сконфигурировать TopologyManager: планировщик + сборка proc_dicts (runtime-хук).

    Цепочка: unwrap_recipe → normalize_blueprint → BlueprintAssembler.assemble
    — та же сборка, что boot (Phase 1). Prototype-специфика (unwrap рецепта v3,
    SystemConfig-defaults) инъецируется через замыкание ``_build_proc_dicts``;
    framework-менеджер TopologyManager про неё не знает.

    Если ``sys_config`` отсутствует в orchestrator_config (тесты, legacy) —
    логирует и выходит без конфигурации (менеджер остаётся «спящим»:
    diff_fn/commands_fn = None → apply вернёт ``not configured``).
    """
    sys_config_dict = orchestrator.get_config("sys_config")
    if not sys_config_dict:
        orchestrator._log_info(
            "[topology-engine] sys_config отсутствует в orchestrator_config — "
            "планировщик не сконфигурирован (тесты/legacy)"
        )
        return

    # Lazy-импорты: prototype-символы, не нужные framework
    from pathlib import Path

    from multiprocess_prototype.backend.assembly import BlueprintAssembler, FullReplacePlanner
    from multiprocess_prototype.backend.assembly.normalize import normalize_blueprint
    from multiprocess_prototype.backend.config.schemas import SystemConfig
    from multiprocess_prototype.backend.launch import (
        PROJECT_ROOT,
        apply_presentation_overlay,
        unwrap_recipe,
    )
    from multiprocess_prototype.recipes.devices_sync import (
        extract_recipe_devices,
        inject_recipe_devices,
    )

    sys_config = SystemConfig.model_validate(sys_config_dict)

    # КРИТИЧНО: наполнить PluginRegistry в ЭТОМ процессе (PM/orchestrator).
    # BlueprintAssembler.assemble зовёт SystemBlueprint.check(), а тот резолвит
    # порты плагинов ТОЛЬКО через PluginRegistry (_find_plugin_entry). На boot
    # discover выполняется в launcher-процессе, но PM спавнится отдельно и реестр
    # НЕ наследует — без discover здесь check() считал бы ВСЕ wire невалидными
    # («источник не найден среди выходов») → BlueprintInvalid → switch рецепта
    # падал бы, не остановив старые процессы. Та же логика, что launch.py boot.
    if sys_config.discovery.auto_discover:
        plugin_paths = [
            str(PROJECT_ROOT / p) if not Path(p).is_absolute() else p for p in sys_config.discovery.plugin_paths
        ]
        # A6 (Ф5.11): тот же единый helper, что на boot (launch.py) — одна копия.
        from multiprocess_framework.modules.app_module import discover as app_discover

        discovered = app_discover(plugin_paths=plugin_paths, service_paths=[]).plugins_discovered
        orchestrator._log_info(f"[topology-engine] discover: {discovered} плагинов в PM-процессе")

    # Слой L1 — сырая секция system.yaml (exclude_unset: слой обязан уметь
    # молчать, иначе рецепт нечем переопределять — см. launch.py, Task 5.12).
    obs_section = sys_config.observability.model_dump(exclude_unset=True)
    log_dir = sys_config.system.log_dir or "logs"

    # PC 3.1 (hot-swap gap fix): прокинуть глобальный telemetry.publish в assembler —
    # тем же способом, что boot (launch.py PC 1.3). Без этого процессы, ПЕРЕСОБРАННЫЕ
    # при hot-swap рецепта (switch), не получали бы глобальный дефолт telemetry.publish
    # из system.yaml → publisher-gate у них не строился бы (TelemetryGate активен только
    # если секция доехала до proc_dict). per-process override живёт в самом blueprint —
    # assembler читает его независимо; здесь закрываем именно ГЛОБАЛЬНЫЙ дефолт.
    telemetry_publish = sys_config.telemetry.publish
    telemetry_dict = telemetry_publish.model_dump() if telemetry_publish is not None else None
    app_config_path = str(orchestrator.get_config("observability_config_path") or "")

    def _active_recipe_path() -> str:
        """Адрес слоя L2 НА МОМЕНТ ЭТОЙ сборки (Task 5.12, блокер ревью 2).

        Резолвится ПОКАЖДЫЙ вызов, а не один раз в конструкторе ассемблера:
        ассемблер живёт всё время работы PM, а рецепт меняется каждым switch.
        Зашитый в конструктор путь означал бы, что пересозданные процессы
        получают адрес ПЕРВОГО рецепта — и сохранённый спутник нового молча
        не применяется (та же живая находка «сохранить не сохраняет», только
        воскрешённая для switch).

        Свежее всего — манифест (``app.yaml: pipeline``): его пишет GUI при
        активации рецепта. Фолбэк — boot-значение из orchestrator_config.
        """
        from_manifest = getattr(orchestrator, "_active_recipe_from_manifest", None)
        if callable(from_manifest):
            resolved = from_manifest()
            if resolved:
                return str(resolved)
        return str(orchestrator.get_config("observability_recipe_path") or "")

    # Патч презентации, наложенный на boot-топологию (None, если презентации нет:
    # бэкенд-вход, --headless, отсутствующий overlay в манифесте). Резолвится ОДИН
    # раз здесь: он свойство запуска, а не рецепта, и от switch к switch не меняется.
    presentation_overlay = orchestrator.get_config("presentation_overlay")

    def _build_proc_dicts(bp: dict) -> dict[str, dict]:
        """unwrap рецепта v3 → presentation-патч → normalize → assemble.

        Та же цепочка, что boot (`launch.SystemBuilder.from_manifest`), включая
        презентационный патч. Без него горячая замена раздавала бы `gui` класс,
        объявленный рецептом, — дренирующее воплощение: сегодня `gui` во всех
        рецептах `protected`, поэтому окно переживает switch, и расхождение лишь
        вечно горит в сигнале конфликта; сними кто-нибудь `protected` — и окно
        Порядок «патч после unwrap, до normalize» взят паритетом с boot, и
        только паритетом: инъекция, переворачивающая его, не изменила НИЧЕГО в
        собранных proc_dict'ах — ассемблер добирает дефолты плагина сам, и
        разница, видимая на промежуточном blueprint (3 ключа против 8), к
        результату исчезает. Написано здесь, чтобы следующий не принял паритет за
        инвариант и не начал его защищать.

        deepcopy входа: unwrap_recipe отдаёт shallow-copy (ссылки внутрь
        исходного blueprint), normalize_blueprint мутирует in-place →
        без deepcopy повторный switch накапливал бы side-effect на IPC-рецепте.
        """
        recipe_path = _active_recipe_path()
        unwrapped = copy.deepcopy(unwrap_recipe(bp))
        if presentation_overlay:
            # deepcopy ПАТЧА, а не только рецепта. `apply_presentation_overlay`
            # сливает пополям поверхностно, поэтому список плагинов патча попадает
            # в топологию ССЫЛКОЙ, а `normalize_blueprint` мутирует его in-place:
            # без копии хранимый overlay обогащался бы per-category defaults на
            # первом же switch и приезжал бы на следующий уже не тем, чем объявлен.
            # Измерено: после одной сборки запись плагина в overlay вырастала с 3
            # ключей до 8.
            unwrapped = apply_presentation_overlay(unwrapped, copy.deepcopy(presentation_overlay))
        # Устройства рецепта (S-25). Секция `devices:` — top-level, сосед
        # `blueprint:`, и `unwrap_recipe` её выбрасывает — поэтому извлечение
        # идёт от СЫРОГО `bp`, а не от `unwrapped`. Без этого шага пересобранный
        # `devices` поднимался бы с пустым хабом: живьём это не жгло только
        # потому, что `devices` во всех рецептах `protected` и не рестартится,
        # — то есть дефект ждал первого снятия флага. Побочно он же был вечным
        # шумом в сигнале расхождения protected: живой конфиг нёс
        # `recipe_devices`, свежая сборка — нет, и `devices` числился
        # разошедшимся при ЛЮБОМ switch, даже на тот же самый рецепт.
        #
        # Место — после патча презентации, до normalize: паритет с boot
        # (`launch.from_manifest`), и только паритет. Никакой проверенной
        # зависимости от порядка тут нет, поэтому и не защищаем её тестом.
        recipe_devices = extract_recipe_devices(bp)
        if recipe_devices:
            recipe_name = str(bp.get("name") or (Path(recipe_path).stem if recipe_path else ""))
            unwrapped = inject_recipe_devices(unwrapped, recipe_devices, recipe_name)
        topology = normalize_blueprint(unwrapped, sys_config)
        # Task 5.13, шаг 7 — что эта пересборка делает с долькой ОРКЕСТРАТОРА:
        # ничего, и это решение, а не пропуск. Она возвращает proc_dict'ы ДЕТЕЙ,
        # а свой слой оркестратор берёт из конверта switch'а
        # (`_recipe_layer_payload` → `_reset_observability_sessions`). Выдай она
        # дольку ещё и здесь — слой ставился бы дважды, из двух источников,
        # и на первом же расхождении победил бы тот, кто пришёл последним.
        # Согласованность держится тем, что спутник у обоих путей кладётся
        # ПОСЛЕДНИМ и одним кодом (`compose_over_base`), из одного файла.
        #
        # ФР-3: спутник в `topology["observability"]` не домерживается — как и на
        # boot (`launch.py`). Эта секция становится БАЗОЙ слоя в конфиге каждого
        # пересобранного процесса, а базу процесс переживает; спутник же обязан
        # оставаться снимаемым — иначе снятый из него ключ воскресал бы вечно.
        # Пересозданный процесс читает спутник сам, на старте
        # (`ProcessModule._apply_boot_observability_layers`), переживший —
        # в ветке switch'а `config.reload`.
        assembler = BlueprintAssembler(
            observability_section=obs_section,
            log_dir=log_dir,
            telemetry_dict=telemetry_dict,
            recipe_path=recipe_path,
            app_config_path=app_config_path,
        )
        return assembler.assemble(topology)

    # Планировщик (BaseManager + ObservableMixin)
    planner = FullReplacePlanner(
        proc_dicts_fn=_build_proc_dicts,
        protected_provider=orchestrator._get_protected_names,
        current_provider=orchestrator._topology_current_names,
        # B-2 (RS-3): живой конфиг protected-процесса для детекции расхождения
        # с новым рецептом (protected не рестартится — расхождение = не тихий успех).
        protected_config_provider=orchestrator.live_process_config,
        logger=orchestrator.logger_manager,
        error=orchestrator.error_manager,
        stats=orchestrator.stats_manager,
    )
    planner.initialize()
    orchestrator._full_replace_planner = planner

    # Сконфигурировать менеджер: diff + commands из планировщика
    orchestrator._topology_manager.configure(
        diff_fn=planner.diff,
        commands_fn=planner.commands,
    )

    orchestrator._log_info(
        f"[topology-engine] сконфигурирован: FullReplacePlanner + BlueprintAssembler (log_dir={log_dir!r})"
    )


def apply_topology_with_display_reload(
    orchestrator: "GenericProcessManagerApp",
    blueprint: dict | None,
    super_apply: Callable[[dict | None], dict],
) -> dict:
    """Применить топологию + переналить DisplayRegistry определениями рецепта (runtime-хук).

    Prototype-override generic ``apply_topology``: извлекает ``display_definitions``
    из входного dict (сырой рецепт или unwrapped topology), reload'ит DisplayRegistry
    ПЕРЕД вызовом generic apply (``super_apply``), откатывает метаданные при rollback.

    SHM НЕ трогает (Решение №1, ADR-DM-003): аллокация кадров продюсеров —
    штатная фаза ``process.provision`` внутри TopologyManager.

    Generic-оркестратор (framework) НЕ знает про display_definitions — это Wire
    prototype-слоя (ADR-130 / Plan displays-in-recipe Task 2.2).
    """
    from dataclasses import asdict

    from multiprocess_framework.modules.display_module import DisplayRegistry

    from multiprocess_prototype.backend.launch import unwrap_recipe

    # --- Извлечь display_definitions из входного blueprint ---
    # Если прилетает сырой рецепт (top-level blueprint + displays) —
    # unwrap_recipe поднимет displays → display_definitions.
    # Если plain topology (уже содержит processes) — вернёт as-is.
    bp = blueprint or {}
    unwrapped = unwrap_recipe(bp) if isinstance(bp, dict) else {}
    defs = unwrapped.get("display_definitions")

    # Edge case плана: display_definitions ОТСУТСТВУЕТ вовсе → no-op для реестра
    # (не чистить зря). reload([]) только когда явно пустой список.
    if defs is None:
        # Ключ отсутствует — не трогаем реестр, вызываем generic apply
        return super_apply(blueprint)

    # --- Снять old_defs ДО reload (Решение №2: rollback) ---
    registry = DisplayRegistry()
    old_defs = [asdict(e) for e in registry.list()]

    # --- reload метаданных (только SHM-поля, без on_orphan — Task 2.3) ---
    registry.reload(defs)

    # --- Вызвать generic apply_topology (snapshot/pause/apply/rollback) ---
    result = super_apply(blueprint)

    # --- Rollback метаданных при неуспехе ---
    if not result.get("success") and result.get("rolled_back"):
        registry.reload(old_defs)
        orchestrator._log_info(
            f"[apply_topology] display_definitions откачены (rolled_back): восстановлено {len(old_defs)} определений"
        )

    return result
