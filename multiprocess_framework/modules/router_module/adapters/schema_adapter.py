# -*- coding: utf-8 -*-
"""
RouterSchemaAdapter — преобразование SchemaBase в описание маршрутов Router'а.

Назначение:
    Адаптер читает FieldMeta каждого поля схемы и извлекает информацию
    маршрутизации (channel, priority). На выходе — реестр каналов, который
    RouterManager может использовать для регистрации каналов и маппинга полей.

Паттерн: Dependency Inversion
    RouterSchemaAdapter реализует ISchemaAdapter (из data_schema_module.interfaces).
    data_schema_module ничего не знает о router_module — зависимость однонаправленная.

Расширяемость:
    - Переопределить _extract_channel_info() для кастомного маппинга FieldRouting.
    - Добавить фильтрацию по access_level через опцию min_access_level.
    - Добавить поддержку вложенных схем через опцию recursive=True.

Использование:
    from multiprocess_framework.modules.router_module.adapters.schema_adapter import RouterSchemaAdapter
    from my_module.config import DrawRegisters

    adapter = RouterSchemaAdapter()
    routes = adapter.adapt(DrawRegisters)
    # {
    #     "control_draw": {
    #         "fields": ["dp", "min_dist"],
    #         "priority": 1,
    #     }
    # }
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Type


class RouterSchemaAdapter:
    """
    Адаптер для преобразования SchemaBase в реестр маршрутов RouterManager.

    Реализует протокол ISchemaAdapter из data_schema_module.interfaces:
        adapt(schema_class, **options) -> Dict[str, Any]
        adapt_instance(schema_instance, **options) -> Dict[str, Any]

    Результат adapt():
        {
            "<channel_name>": {
                "fields": ["field_a", "field_b"],   # поля, маршрутизируемые в канал
                "priority": 1,                       # приоритет канала (из FieldRouting)
            },
            ...
        }
    """

    def adapt(self, schema_class: Type, **options) -> Dict[str, Any]:
        """
        Преобразовать класс схемы в реестр маршрутов.

        Args:
            schema_class: Класс схемы (наследник SchemaBase).
            **options:
                min_access_level (int): Минимальный уровень доступа для включения поля.
                include_no_channel (bool): Включить поля без канала в ключ "__unrouted__".

        Returns:
            Dict[channel_name, {"fields": [...], "priority": int}]
        """
        routes: Dict[str, Any] = {}
        min_level: int = options.get("min_access_level", 0)
        include_unrouted: bool = options.get("include_no_channel", False)

        if not hasattr(schema_class, "get_all_fields_meta"):
            return routes

        for field_name, meta in schema_class.get_all_fields_meta().items():
            # Фильтр по уровню доступа
            if getattr(meta, "access_level", 0) < min_level:
                continue

            channel, priority = self._extract_channel_info(meta)

            if channel is None:
                if include_unrouted:
                    routes.setdefault("__unrouted__", {"fields": [], "priority": 0})
                    routes["__unrouted__"]["fields"].append(field_name)
                continue

            if channel not in routes:
                routes[channel] = {"fields": [], "priority": priority}

            routes[channel]["fields"].append(field_name)

        return routes

    def adapt_instance(self, schema_instance: Any, **options) -> Dict[str, Any]:
        """
        Преобразовать экземпляр схемы в реестр маршрутов с текущими значениями.

        Args:
            schema_instance: Экземпляр SchemaBase.
            **options:
                include_values (bool): Добавить текущие значения полей в результат.
                Остальные опции передаются в adapt().

        Returns:
            Dict[channel_name, {"fields": [...], "priority": int, "values"?: {...}}]
        """
        routes = self.adapt(type(schema_instance), **options)

        if options.get("include_values") and hasattr(schema_instance, "model_dump"):
            data = schema_instance.model_dump()
            for channel_info in routes.values():
                channel_info["values"] = {
                    field: data.get(field)
                    for field in channel_info["fields"]
                }

        return routes

    def get_all_channels(self, schema_class: Type) -> List[str]:
        """
        Получить список всех каналов, используемых схемой.

        Удобный метод для регистрации каналов в RouterManager при инициализации.
        """
        routes = self.adapt(schema_class)
        return list(routes.keys())

    # -------------------------------------------------------------------------
    # Внутренние методы (переопределяемые в подклассах)
    # -------------------------------------------------------------------------

    def _extract_channel_info(self, meta: Any) -> tuple[Optional[str], int]:
        """
        Извлечь (channel, priority) из FieldMeta.

        Поддерживает оба формата routing:
            - dict:         {"channel": "ctrl", "priority": 1}
            - FieldRouting: meta.routing.channel, meta.routing.priority
        """
        routing = getattr(meta, "routing", None)
        if not routing:
            return None, 0

        if isinstance(routing, dict):
            channel = routing.get("channel")
            priority = int(routing.get("priority", 0))
        else:
            channel = getattr(routing, "channel", None)
            priority = int(getattr(routing, "priority", 0))

        return channel, priority
