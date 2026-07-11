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

from multiprocess_framework.modules.data_schema_module import process
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
    """

    def __init__(
        self,
        observability_dict: dict[str, Any],
        log_dir: str = "logs",
    ) -> None:
        self._observability_dict = observability_dict
        self._log_dir = log_dir

    def assemble(self, blueprint_dict: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Собрать proc_dict для каждого процесса из blueprint-топологии.

        Цепочка (паритет с дорогой A boot):
        1. ``SystemBlueprint.model_validate(blueprint_dict)`` — копирует, не мутирует вход.
        2. ``topology.check()`` → при ошибках ``raise BlueprintInvalid``.
        3. ``topology.build_configs()`` → список ``GenericProcessConfig``.
        4. Для каждого cfg: если ``cfg.log_dir`` пуст → ``cfg.log_dir = self._log_dir``.
        5. ``name, proc_dict = process(cfg)`` — framework-конвертер.
        6. ``merge_managers(proc_dict["managers"], observability_dict)``.
        7. ``merge_with_defaults(proc_dict, DEFAULT_PROCESS_SCHEMA)`` — нормализация
           (те же дефолты, что ``SystemLauncher.add_process``; идемпотентно).

        Args:
            blueprint_dict: Нормализованный blueprint dict (per-category defaults
                уже применены снаружи через ``normalize_blueprint``).

        Returns:
            ``{process_name: normalized_proc_dict}`` — готов к ``add_process``.

        Raises:
            BlueprintInvalid: если ``topology.check()`` вернул ошибки.
        """
        # model_validate создаёт КОПИЮ — входной dict не мутируется.
        topology = SystemBlueprint.model_validate(blueprint_dict)

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
            proc_dict = merge_with_defaults(proc_dict, DEFAULT_PROCESS_SCHEMA)
            result[name] = proc_dict

        return result
