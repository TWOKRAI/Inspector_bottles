# -*- coding: utf-8 -*-
"""SharedResourcesManagerConfig — SchemaBase-конфиг фасада SharedResourcesManager.

Управляет поведением пяти внутренних компонентов SRM:
ConfigStore, ProcessStateRegistry, QueueRegistry, EventManager, MemoryManager.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("shared_resources_manager")
class SharedResourcesManagerConfig(SchemaBase):
    """
    Конфигурация SharedResourcesManager — центрального модуля фреймворка.

    Используется при создании SRM:
        config = SharedResourcesManagerConfig(default_queue_maxsize=200)
        srm = SharedResourcesManager(config=config.model_dump())
    """

    # -- Идентификация --
    manager_name: Annotated[str, FieldMeta("Имя менеджера")] = "SharedResourcesManager"

    # -- ObservableMixin (наследование от BaseManager) --
    auto_proxy: Annotated[bool, FieldMeta("Авто-прокси для Observable")] = True
    observable_config: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta("Конфиг ObservableMixin (опционально)"),
    ] = None

    # -- QueueRegistry: параметры по умолчанию для очередей --
    default_queue_maxsize: Annotated[
        int, FieldMeta("Размер очереди по умолчанию (0 = безлимитная)", min=0, max=100_000)
    ] = 0

    # -- EventManager: параметры --
    event_wait_poll_interval: Annotated[
        float, FieldMeta("Интервал polling в wait_for_event(), сек", min=0.01, max=5.0)
    ] = 0.5

    # -- MemoryManager: параметры SharedMemory --
    default_memory_coll: Annotated[
        int, FieldMeta("Кол-во слотов SharedMemory по умолчанию", min=1, max=64)
    ] = 2
    cleanup_stale_shm_on_init: Annotated[
        bool, FieldMeta("Очистить stale SharedMemory при инициализации")
    ] = True

    # -- Стандартные события: автоматически создаются для каждого процесса --
    standard_events: Annotated[
        list, FieldMeta("Список стандартных событий для каждого процесса")
    ] = ["stop", "pause"]
