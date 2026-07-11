"""Back-compat шим (C6 шаг c): SystemBlueprint/ProcessConfig/Wire переехали в
``process_manager_module/topology/blueprint.py`` (системная топология — дом оркестратора,
а не модуля одного процесса). Здесь — временный ре-экспорт на переходный период, чтобы не
править ~9 импортёров одним коммитом. Call sites мигрируют отдельными follow-up коммитами;
после миграции этот шим удаляется.

НЕ добавлять сюда новую логику — канон в process_manager_module.topology.blueprint.
"""

from __future__ import annotations

from ...process_manager_module.topology.blueprint import (
    ProcessConfig,
    SystemBlueprint,
    Wire,
)

__all__ = ["ProcessConfig", "SystemBlueprint", "Wire"]
