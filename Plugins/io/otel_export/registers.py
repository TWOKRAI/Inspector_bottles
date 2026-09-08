# -*- coding: utf-8 -*-
"""OtelExportRegisters — дверь конфига плагина. Производная от схемы сервиса.

**Одно поле переопределено (другой дефолт), остальные — как в
`Services/otel_export/config.py`.** Поля, `FieldMeta` и валидация по-прежнему
живут там; здесь — подкласс с регистрацией в реестре схем, чтобы GUI-панель
и `set_config` видели регистр обычным образом.

Почему так, а не как у `telemetry_sink` (где поля объявлены в регистрах):
у экспортёра есть сервис-владелец, а слои `framework -> Services -> Plugins`
запрещают `Services` импортировать `Plugins`. Значит источник полей обязан быть
в сервисе, иначе он их не увидит. Две таблицы полей — прямое нарушение
критерия C2 (наборы обязаны совпадать множеством). См. ADR-OTEL-003.

**Почему `endpoint` здесь с дефолтом `""`, хотя в конфиге сервиса он
обязателен.** `plugin_orchestrator._collect_register_schemas` строит
managed-регистр строкой `instance = reg_item()` — всегда без аргументов.
С обязательным полем без дефолта это падает `ValidationError` прямо на
конструкторе, регистра у плагина не появляется вовсе (ни GUI-двери, ни
`register_update`), и критерий Task 3.1 («фрагмент без `endpoint` → плагин в
`error`») недостижим — до `error` дело не доходит. У `SchemaBase` не выставлен
`validate_default`, поэтому пустой дефолт не проверяется валидатором
`_endpoint_not_blank` при построении самого регистра: `OtelExportRegisters()`
живёт. Отказ переезжает на шаг позже — в `OtelExportConfig(**reg.model_dump())`
внутри `configure()` плагина (Ф2.1), где пустой `endpoint` уже отвергается
с именем ключа. Вариант (а) из ADR-OTEL-003; вариант (в) — строить
managed-регистр из значений фрагмента, а не из дефолтов — долг closure,
репродукция там же.

Метод `readback()` наследуется от `OtelExportConfig`: эффективные значения —
свойство схемы, а не регистра.
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import FieldMeta, register_schema

from Services.otel_export.config import OtelExportConfig

__all__ = ["OtelExportRegisters"]


@register_schema("OtelExportRegistersV1")
class OtelExportRegisters(OtelExportConfig):
    """Регистры плагина `otel_export` — та же схема, что у сервиса, минус дефолт `endpoint`.

    `FieldMeta` у `endpoint` повторяет `OtelExportConfig` целиком — переопределяется
    только `= ""`, иначе GUI-панель потеряла бы заголовок и подсказку поля
    (в pydantic v2 переобъявление поля без `Annotated[...]` в подклассе стирает
    метаданные родителя, а не наследует их — проверено прогоном).
    """

    endpoint: Annotated[
        str,
        FieldMeta(
            "Endpoint",
            info=(
                "Адрес приёмника OTLP/HTTP ВМЕСТЕ С ПУТЁМ СИГНАЛА, "
                "напр. http://127.0.0.1:4318/v1/logs — SDK шлёт по нему дословно, "
                "адрес без пути даёт 404. "
                "Обязателен фактически (см. Services/otel_export/config.py): "
                "здесь дефолт пуст только для того, чтобы managed-регистр "
                "успевал построиться без аргументов — пустое значение "
                "отвергается на шаге `configure()` плагина, с именем ключа"
            ),
        ),
    ] = ""
