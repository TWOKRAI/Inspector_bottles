# -*- coding: utf-8 -*-
"""OtelExportRegisters — дверь конфига плагина. Производная от схемы сервиса.

**Ни одного переобъявленного поля.** Поля, дефолты, `FieldMeta` и валидация
живут в `Services/otel_export/config.py`; здесь — подкласс с регистрацией в
реестре схем, чтобы GUI-панель и `set_config` видели регистр обычным образом.

Почему так, а не как у `telemetry_sink` (где поля объявлены в регистрах):
у экспортёра есть сервис-владелец, а слои `framework -> Services -> Plugins`
запрещают `Services` импортировать `Plugins`. Значит источник полей обязан быть
в сервисе, иначе он их не увидит. Две таблицы полей — прямое нарушение
критерия C2 (наборы обязаны совпадать множеством). См. ADR-OTEL-003.

Метод `readback()` наследуется от `OtelExportConfig`: эффективные значения —
свойство схемы, а не регистра.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.plugins import register_schema

from Services.otel_export.config import OtelExportConfig

__all__ = ["OtelExportRegisters"]


@register_schema("OtelExportRegistersV1")
class OtelExportRegisters(OtelExportConfig):
    """Регистры плагина `otel_export` — те же параметры, что у сервиса.

    Пустой по телу класс здесь — не заглушка: он даёт регистру собственное имя
    в реестре схем (`OtelExportRegistersV1`) и точку привязки для
    `register_bindings`, не заводя второго определения полей.
    """
