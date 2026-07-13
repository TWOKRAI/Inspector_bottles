# -*- coding: utf-8 -*-
"""RouterManagerConfig — плоская схема RouterManager."""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("router_manager")
class RouterManagerConfig(SchemaBase):
    """Конфигурация RouterManager (метаданные; рантайм подключается отдельно)."""

    manager_name: Annotated[str, FieldMeta("Имя роутера")] = "RouterManager"
    send_queue_size: Annotated[int, FieldMeta("Размер очереди AsyncSender", min=1, max=65536)] = 512
    dispatch_strategy: Annotated[
        Literal["exact", "pattern", "fallback", "chain"],
        FieldMeta("Стратегия диспетчера исходящих"),
    ] = "exact"
    dispatcher_key_field: Annotated[str, FieldMeta("Поле ключа в сообщении")] = "command"
    duplicate_messages_to_logger: Annotated[
        bool,
        FieldMeta(
            "Дублировать исходящие сообщения в LoggerManager",
            info="Используется ProcessManagers при инициализации.",
        ),
    ] = True
    use_kind_channels: Annotated[
        bool,
        FieldMeta(
            "Резолвить исходящие через kind-каналы {proc}_{kind} (Ф7 G.2)",
            info=(
                "OFF (дефолт) — прежний резолв через dispatcher/targets, бит-в-бит. "
                "ON — resolve_channel_kind → channel_name(target, kind). "
                "env-override: MULTIPROCESS_USE_KIND_CHANNELS."
            ),
        ),
    ] = False
