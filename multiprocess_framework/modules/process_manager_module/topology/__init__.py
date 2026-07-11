"""topology — системная топология: SchemaBase-чертёж системы.

C6 шаг (c): `SystemBlueprint`/`ProcessConfig`/`Wire` — чертёж ВСЕЙ системы (много
процессов + wires), физически переехал сюда из `process_module/generic/` (модуля ОДНОГО
процесса). Дом — `process_manager_module` (оркестратор системы), который эту топологию
и собирает; снят реверс-паттерн «PM лезет во внутренности process_module за системным
артефактом» (см. c6-pipeline-engine-design.md §1.4/§5(c)).

`GenericProcessConfig`/`PluginConfig` (per-process конфиг) ОСТАЮТСЯ в `process_module`;
`build_configs()` возвращает их (process_manager_module → process_module, framework-
internal L9→L8, разрешено).
"""

from .blueprint import ProcessConfig, SystemBlueprint, Wire

__all__ = ["ProcessConfig", "SystemBlueprint", "Wire"]
