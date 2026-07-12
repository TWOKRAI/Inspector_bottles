"""orchestrator.py -- ProcessManagerProcessApp прототипа (Ф5.12).

Тонкая композиция: ``GenericProcessManagerApp`` (generic-оркестратор яруса 2,
app_module) + два прототипных **runtime-хука**. Класс лишь подключает хуки в
seam'ы generic-оркестратора; их тела (Inspector-специфика — BlueprintAssembler,
DisplayRegistry) вынесены в :mod:`multiprocess_prototype.backend.orchestrator_hooks`.

Generic-часть (StateStore из build-time хуков, observability-watcher, shutdown)
унаследована от ``GenericProcessManagerApp`` — здесь не дублируется.

Оба хука — runtime-сорта: резолвятся child-side через ``orchestrator_class_path``
(callable не пиклится через spawn).
"""

from __future__ import annotations

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
