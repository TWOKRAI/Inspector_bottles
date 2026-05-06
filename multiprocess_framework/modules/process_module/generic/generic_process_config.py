"""GenericProcessConfig + PluginConfig — конфигурация для GenericProcess.

PluginConfig — базовый SchemaBase для конфига одного плагина.
GenericProcessConfig — ProcessLaunchConfig с list[dict] плагинов.

Dict at Boundary: plugins хранятся как list[dict] (model_dump()),
потому что proc_dict пересекает границу процессов.
"""

from __future__ import annotations

from typing import Annotated, Any

from ...data_schema_module import FieldMeta, SchemaBase, register_schema
from ..configs.process_launch_config import ProcessLaunchConfig


@register_schema("PluginConfigV1")
class PluginConfig(SchemaBase):
    """Базовый конфиг одного плагина.

    Наследники добавляют plugin-specific поля.
    plugin_class + plugin_name — обязательные для GenericProcess.
    """

    plugin_class: Annotated[
        str,
        FieldMeta("Plugin class", info="Dotted path к классу ProcessModulePlugin."),
    ] = ""

    plugin_name: Annotated[
        str,
        FieldMeta("Plugin name", info="Уникальное имя плагина внутри процесса."),
    ] = ""

    category: Annotated[
        str,
        FieldMeta("Category", info="source | processing | output"),
    ] = ""

    @property
    def memory(self) -> dict[str, Any] | None:
        """SHM layout для этого плагина. Override в наследниках."""
        return None


@register_schema("GenericProcessConfigV1")
class GenericProcessConfig(ProcessLaunchConfig):
    """ProcessLaunchConfig для GenericProcess.

    plugins — список dict'ов (PluginConfig.model_dump()).
    GenericProcess читает их в _init_application_threads().
    """

    process_class: str = (
        "multiprocess_framework.modules.process_module"
        ".generic.generic_process.GenericProcess"
    )

    plugins: Annotated[
        list[dict[str, Any]],
        FieldMeta("Plugins", info="Список конфигов плагинов (dict)."),
    ] = []

    # --- Phase 5: Data Pipeline config ---

    chain_targets: Annotated[
        list[str],
        FieldMeta("Chain targets", info="Default routing targets после pipeline (Q1)."),
    ] = []

    queue_size: Annotated[
        int,
        FieldMeta("Queue size", info="Размер internal chain_queue.", min=1, max=1024),
    ] = 64

    lag_alert_threshold_sec: Annotated[
        float,
        FieldMeta("Lag alert threshold", info="Backpressure alert порог (Q6).", min=0.1),
    ] = 2.0

    source_target_fps: Annotated[
        float,
        FieldMeta("Source target FPS", info="Целевой FPS для source-плагинов.", min=1.0),
    ] = 25.0

    error_max_consecutive_fails: Annotated[
        int,
        FieldMeta("Error max fails", info="Circuit breaker порог (Q7).", min=1),
    ] = 5

    error_auto_reset_sec: Annotated[
        float,
        FieldMeta("Error auto-reset", info="Auto-reset circuit breaker (Q7).", min=1.0),
    ] = 60.0

    error_critical_plugins: Annotated[
        list[str],
        FieldMeta("Critical plugins", info="Имена критических плагинов (Q7)."),
    ] = []

    @property
    def memory(self) -> dict[str, Any] | None:
        """Агрегация SHM layout из всех плагинов.

        Каждый dict в plugins может содержать поля,
        из которых PluginConfig-наследник формирует memory.
        Но т.к. plugins — list[dict], мы не можем вызвать .memory напрямую.

        Для агрегации используем _plugin_configs — список PluginConfig-инстансов,
        если они были переданы через helper-метод from_plugins().
        """
        if not hasattr(self, "_plugin_memory_cache"):
            return None
        return self._plugin_memory_cache or None

    @classmethod
    def from_plugins(
        cls,
        process_name: str,
        plugin_configs: list[PluginConfig],
        **kwargs: Any,
    ) -> GenericProcessConfig:
        """Создать GenericProcessConfig из списка PluginConfig-объектов.

        Автоматически:
        - Сериализует каждый PluginConfig в dict для plugins
        - Агрегирует memory из всех плагинов
        """
        plugins_dicts = [pc.model_dump() for pc in plugin_configs]

        # Агрегация SHM
        merged_memory: dict[str, Any] = {}
        for pc in plugin_configs:
            mem = pc.memory
            if mem:
                merged_memory.update(mem)

        instance = cls(
            process_name=process_name,
            plugins=plugins_dicts,
            **kwargs,
        )
        # Кэшируем агрегированную memory
        object.__setattr__(instance, "_plugin_memory_cache", merged_memory)
        return instance

    def build(self) -> tuple[str, dict[str, Any]]:
        """Build proc_dict с плагинами в config['plugins']."""
        name, proc_dict = super().build()
        # plugins уже в payload через model_dump() в super().build(),
        # но нужно убедиться что они в config
        proc_dict["config"]["plugins"] = self.plugins
        return name, proc_dict
