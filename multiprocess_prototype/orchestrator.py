"""orchestrator.py -- ProcessManagerProcessApp прототипа (Ф5.12).

Тонкая композиция: ``GenericProcessManagerApp`` (generic-оркестратор яруса 2,
app_module) + два прототипных **runtime-хука**. Класс лишь подключает хуки в
seam'ы generic-оркестратора; их тела (Inspector-специфика — BlueprintAssembler,
DisplayRegistry) вынесены в :mod:`multiprocess_prototype.backend.orchestrator_hooks`.

Generic-часть (StateStore из build-time хуков, observability-watcher, shutdown)
унаследована от ``GenericProcessManagerApp`` — здесь не дублируется.

Оба хука — runtime-сорта: резолвятся child-side через ``orchestrator_class_path``
(callable не пиклится через spawn).

Task 1b.1 (ADR-RCP-007): хаб хостит сервис рецептов ``recipe.*`` —
:meth:`ProcessManagerProcessApp._register_builtin_commands` дорегистрирует
обработчики ``RecipeService`` поверх встроенных команд PM.
"""

from __future__ import annotations

import os
from pathlib import Path

from multiprocess_framework.modules.app_module.orchestrator import GenericProcessManagerApp

from multiprocess_prototype.backend.orchestrator_hooks import (
    apply_topology_with_display_reload,
    configure_topology_engine,
)


class ProcessManagerProcessApp(GenericProcessManagerApp):
    """Прототипный оркестратор = generic + два runtime-хука.

    * ``_configure_runtime`` (seam) → :func:`configure_topology_engine`:
      движок горячей замены (FullReplacePlanner + BlueprintAssembler).
    * ``apply_topology`` (override) → :func:`apply_topology_with_display_reload`:
      reload DisplayRegistry определениями рецепта вокруг generic apply.

    StateStore (``initial_state``/``state_throttle_rules``), observability-watcher
    и shutdown — generic, унаследованы от ``GenericProcessManagerApp``.
    """

    def _configure_runtime(self) -> None:
        """Runtime-хук: сконфигурировать прототипный topology-engine (после base-init)."""
        configure_topology_engine(self)

    def apply_topology(self, blueprint: dict | None) -> dict:
        """Runtime-хук: reload DisplayRegistry вокруг generic apply_topology."""
        return apply_topology_with_display_reload(self, blueprint, super().apply_topology)

    def _register_builtin_commands(self) -> None:
        """Встроенные команды PM + сервис рецептов ``recipe.*`` (Task 1b.1).

        Сервис нужен манифест: из него каталог рецептов (``recipes:``) и
        «последний активный» (``pipeline:``). Нет манифеста или ``recipes:`` —
        команды не регистрируются (честное «unknown command», а не сервис над
        угаданным каталогом).
        """
        super()._register_builtin_commands()
        if not self.command_manager:
            return
        manifest_path = str(self.get_config("manifest_path") or "")
        if not manifest_path:
            self._log_warning("[recipe] manifest_path не задан — recipe.* не зарегистрированы")
            return
        try:
            service = build_recipe_service(self, Path(manifest_path))
        except Exception as exc:  # noqa: BLE001 — сервис не должен ронять хаб
            self._log_error(f"[recipe] сервис рецептов не поднят ({manifest_path}): {exc}")
            return
        if service is None:
            self._log_warning(f"[recipe] в манифесте нет recipes: ({manifest_path}) — recipe.* не зарегистрированы")
            return
        for cmd_name, handler in service.handlers().items():
            self.command_manager.register_command(
                cmd_name,
                handler,
                metadata={"description": f"Сервис рецептов (ADR-RCP-007): {cmd_name}"},
                tags=["system"],
            )


def build_recipe_service(pm, manifest_path: Path):
    """Собрать ``RecipeService`` хаба над манифестом; ``None`` — в манифесте нет ``recipes:``.

    * ``apply_topology`` — собственная команда PM ``_cmd_topology_apply``
      (debounce, ретаргет L2, откат — не обходятся);
    * ``persist_active`` — ``ManifestStore.set_pipeline`` значением относительно
      каталога манифеста (``recipes/<slug>.yaml`` — как ``persist_pipeline_choice``);
    * ``read_active`` — stem ``pipeline:``, если он лежит в каталоге рецептов.
    """
    from multiprocess_framework.modules.app_module import ManifestStore
    from multiprocess_framework.modules.recipe.service import RecipeService

    from multiprocess_prototype.backend.recipe_format_hook import InspectorRecipeFormatHook

    store = ManifestStore(manifest_path)
    recipes_dir = store.load().recipes
    if recipes_dir is None:
        return None
    recipes_dir = Path(recipes_dir).resolve()
    manifest_dir = manifest_path.resolve().parent

    def persist_active(path: Path) -> object:
        return store.set_pipeline(Path(os.path.relpath(Path(path).resolve(), manifest_dir)).as_posix())

    def read_active() -> str | None:
        pipeline = Path(store.load().pipeline).resolve()
        if pipeline.suffix == ".yaml" and pipeline.parent == recipes_dir:
            return pipeline.stem
        return None

    return RecipeService(
        recipes_dir=recipes_dir,
        hook=InspectorRecipeFormatHook(),
        apply_topology=pm._cmd_topology_apply,
        persist_active=persist_active,
        read_active=read_active,
    )
