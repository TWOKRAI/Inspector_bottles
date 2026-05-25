"""_adr_layers.py — ручной реестр модулей и их слоёв.

Единственное «ручное» место в sync-каркасе: порядок и слои модулей
копируют таблицу «Модульные решения» из корневого DECISIONS.md.
При добавлении нового модуля — добавь строку в MODULE_LAYERS
(или в MODULES_WITHOUT_LOCAL_ADR, если у модуля нет локальных ADR).
"""

from __future__ import annotations

# Порядок соответствует таблице §«Модульные решения» в
# multiprocess_framework/DECISIONS.md (строки 1909–1930).
# Каждый кортеж: (имя_модуля, слой).
# Включены ТОЛЬКО модули с локальными ADR-кодами (ADR-{CODE}-NNN).
MODULE_LAYERS: list[tuple[str, str]] = [
    ("base_manager", "Foundation"),
    ("data_schema_module", "Foundation"),
    ("dispatch_module", "Routing primitives"),
    ("channel_routing_module", "Routing primitives"),
    ("logger_module", "Observability"),
    ("config_module", "Resources & Config"),
    ("message_module", "Messaging"),
    ("router_module", "Messaging"),
    ("worker_module", "Command & Work"),
    ("process_module", "Process"),
    ("command_module", "Command & Work"),
    ("shared_resources_module", "Infrastructure"),
    ("process_manager_module", "Orchestration"),
    ("error_module", "Observability"),
    ("statistics_module", "Observability"),
    ("sql_module", "Data & SQL"),
    ("registers_module", "Infrastructure / registers"),
    ("console_module", "UI / Console"),
    ("state_store_module", "Resources & Config"),
    ("chain_module", "Command & Work"),
    ("actions_module", "Command & Work"),
    ("service_module", "Services & Lifecycle"),
]

# Модули, у которых есть DECISIONS.md, но нет локального ADR-кода
# (содержат только ссылки на глобальные ADR).
MODULES_WITHOUT_LOCAL_ADR: set[str] = {"frontend_module"}
