"""BlueprintAssembler — stateless сборщик proc_dict из blueprint-топологии.

Трансформирует нормализованный blueprint dict в словарь ``{name: proc_dict}``,
готовый для ``SystemLauncher.add_process``.  Внутри — ТОЛЬКО framework-символы;
app-специфика (per-category defaults из ``SystemConfig``) применяется СНАРУЖИ
через ``normalize_blueprint`` (carve-out-ready).

**Контракт:**
- Чистая функция: без I/O, без мутации входного dict, детерминирована.
- ``assemble`` НЕ импортирует ``SystemConfig`` / ``multiprocess_prototype.*``.
- Невалидный blueprint → ``BlueprintInvalid`` (не ``sys.exit``).

Эталон поведения — дорога A (boot через ``SystemBuilder.build``), ВКЛЮЧАЯ
``merge_with_defaults(proc_dict, DEFAULT_PROCESS_SCHEMA)``.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.data_schema_module import deep_merge, process
from multiprocess_framework.modules.data_schema_module.core.helpers import (
    merge_with_defaults,
)
from multiprocess_framework.modules.process_manager_module.launcher.schema import (
    DEFAULT_PROCESS_SCHEMA,
)
from multiprocess_framework.modules.process_module.configs.managers_config import (
    merge_managers,
)
from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
    SystemBlueprint,
)


class BlueprintInvalid(Exception):
    """Ошибка валидации blueprint-топологии.

    Атрибут ``errors`` содержит список строк — описаний конкретных ошибок.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"Blueprint validation failed: {errors}")


class BlueprintAssembler:
    """Stateless сборщик: нормализованный blueprint dict → {name: proc_dict}.

    Параметры конструктора — контекст boot-сборки, которые нельзя вычислить
    из самого blueprint:

    - ``observability_dict`` — уже развёрнутый overlay (``expand_observability``
      делается снаружи). Применяется к ``proc_dict["managers"]`` каждого процесса.
    - ``log_dir`` — каталог логов, выставляется на ``cfg.log_dir`` если тот пуст
      (паритет с launch.py п.5: log_dir выставляется МЕЖДУ build_configs и process).
    - ``telemetry_dict`` (PC 1.3) — глобальный дефолт секции ``telemetry.publish``
      (``TelemetryPublishConfig``-форма: ``default_interval_sec`` + ``metrics``) ИЛИ
      ``None``, если глобально не задан. **В отличие от** ``observability_dict`` —
      НЕ инжектится безусловно: ``proc_dict["config"]["telemetry"]`` появляется
      ТОЛЬКО когда телеметрия реально задана (этот параметр ИЛИ per-process
      ``blueprint.processes[].telemetry``). Нет ни того, ни другого → ключ
      ``telemetry`` в proc_dict отсутствует вовсе — обратная совместимость с PC 1.2
      (``TelemetryGate`` строится только если секция присутствует).
    """

    def __init__(
        self,
        observability_dict: dict[str, Any],
        log_dir: str = "logs",
        telemetry_dict: dict[str, Any] | None = None,
    ) -> None:
        self._observability_dict = observability_dict
        self._log_dir = log_dir
        self._telemetry_dict = telemetry_dict

    def assemble(self, blueprint_dict: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Собрать proc_dict для каждого процесса из blueprint-топологии.

        Цепочка (паритет с дорогой A boot):
        1. ``SystemBlueprint.model_validate(blueprint_dict)`` — копирует, не мутирует вход.
        2. ``topology.infer_missing_inspectors()`` — join/inspector из wires (Ф4.7):
           процессам без явного ``inspector`` структурно выводится ``{mode: join, ...}``
           по графу связей, ДО ``check()``/``build_configs()``.
        3. ``topology.check()`` → при ошибках ``raise BlueprintInvalid``.
        4. ``topology.build_configs()`` → список ``GenericProcessConfig``.
        5. Для каждого cfg: если ``cfg.log_dir`` пуст → ``cfg.log_dir = self._log_dir``.
        6. ``name, proc_dict = process(cfg)`` — framework-конвертер.
        7. ``merge_managers(proc_dict["managers"], observability_dict)``.
        8. PC 1.3: ``proc_dict["config"]["telemetry"]`` — ТОЛЬКО если задано (глобально
           через ``telemetry_dict`` конструктора ИЛИ per-process
           ``blueprint.processes[].telemetry``), см. ``_resolve_telemetry``.
        9. ``merge_with_defaults(proc_dict, DEFAULT_PROCESS_SCHEMA)`` — нормализация
           (те же дефолты, что ``SystemLauncher.add_process``; идемпотентно).

        Args:
            blueprint_dict: Нормализованный blueprint dict (per-category defaults
                уже применены снаружи через ``normalize_blueprint``).

        Returns:
            ``{process_name: normalized_proc_dict}`` — готов к ``add_process``.

        Raises:
            BlueprintInvalid: если ``topology.check()`` вернул ошибки.
        """
        # PC 1.3: per-process telemetry override читаем из СЫРОГО blueprint_dict ДО
        # model_validate — ProcessConfig (SchemaBase) не объявляет typed-поле
        # telemetry (вне Files-скоупа этой задачи), поэтому extra=ignore молча
        # отбросил бы неизвестный ключ при валидации. blueprint_dict здесь ещё не
        # тронут model_validate (копирует, не мутирует), поэтому raw-чтение безопасно.
        per_process_telemetry = self._extract_per_process_telemetry(blueprint_dict)

        # model_validate создаёт КОПИЮ — входной dict не мутируется.
        topology = SystemBlueprint.model_validate(blueprint_dict)

        # Ф4.7: join/inspector из wires — структурный вывод ДО check()/build_configs()
        # (снимает костыль _hoist_inspector_from_metadata; см. infer_missing_inspectors).
        topology.infer_missing_inspectors()

        errors = topology.check()
        if errors:
            raise BlueprintInvalid(errors)

        configs = topology.build_configs()

        # Паритет п.5 дороги A: log_dir выставляется на GenericProcessConfig
        # (наследник ProcessLaunchConfig) МЕЖДУ build_configs и process(cfg).
        for cfg in configs:
            if not cfg.log_dir:
                cfg.log_dir = self._log_dir

        result: dict[str, dict[str, Any]] = {}
        for cfg in configs:
            name, proc_dict = process(cfg)
            proc_dict["managers"] = merge_managers(
                proc_dict.get("managers", {}),
                self._observability_dict,
            )
            override = per_process_telemetry.get(name)
            telemetry_section = self._resolve_telemetry(override)
            if telemetry_section is not None:
                proc_dict["config"]["telemetry"] = telemetry_section
            # Task 2.2 (находка C): сохранить СЫРУЮ per-process дельту рецепта (publish-уровень)
            # отдельно от уже слитой секции telemetry. config.reload из файла несёт только
            # GLOBAL publish; boot мержил global+override — reload обязан тоже. Ключ появляется
            # ТОЛЬКО у процессов с override (иначе boot ≡ reload без него и так совпадают).
            if override is not None:
                proc_dict["config"]["telemetry_override"] = override
            proc_dict = merge_with_defaults(proc_dict, DEFAULT_PROCESS_SCHEMA)
            result[name] = proc_dict

        return result

    @staticmethod
    def _extract_per_process_telemetry(blueprint_dict: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Снять per-process ``telemetry`` override из СЫРОГО blueprint (до model_validate).

        Возвращает ``{process_name: telemetry_dict}`` для процессов, у которых в raw
        dict реально есть ключ ``telemetry`` (dict). Другие процессы в результат не
        попадают — их отсутствие в мапе означает «нет per-process override».
        """
        overrides: dict[str, dict[str, Any]] = {}
        for proc in blueprint_dict.get("processes") or []:
            if not isinstance(proc, dict):
                continue
            name = proc.get("process_name")
            telemetry = proc.get("telemetry")
            if name and isinstance(telemetry, dict):
                overrides[name] = telemetry
        return overrides

    def _resolve_telemetry(self, override: dict[str, Any] | None) -> dict[str, Any] | None:
        """Слить глобальный default (конструктор) с per-process override → секция ``telemetry``.

        Возвращает ``None``, если ТЕЛЕМЕТРИЯ НЕ задана нигде (ни глобально, ни у
        этого процесса) — тогда вызывающий код НЕ кладёт ключ ``telemetry`` в
        ``proc_dict["config"]`` вовсе (обратная совместимость с PC 1.2: нет секции →
        ``TelemetryGate`` не строится, публикация как раньше).

        Merge-семантика (глубокий merge, per-process побеждает): ``metrics.<name>``
        per-process перекрывает одноимённую global-запись (остальные global-метрики
        сохраняются); ``default_interval_sec`` per-process перекрывает global целиком.
        """
        # Различаем «ключ telemetry отсутствует» (override is None — процесса нет в
        # мапе _extract_per_process_telemetry) и «ключ задан явно, но пуст» (override
        # == {}). Пустой dict — намеренное «включить секцию с дефолтами» (симметрично
        # задокументированной семантике TelemetrySection.publish: {} на глобальном
        # уровне); `not override` схлопнул бы его в «не задано» — молча не то.
        if self._telemetry_dict is None and override is None:
            return None
        merged_publish = deep_merge(self._telemetry_dict or {}, override or {})
        return {"publish": merged_publish}
