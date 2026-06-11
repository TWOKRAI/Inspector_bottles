"""DeviceHubRegisters — параметры и телеметрия плагина device_hub.

register = единый источник runtime-параметров + FieldMeta для авто-генерации
config-виджета в инспекторе Pipeline/Plugins.
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("DeviceHubRegistersV1")
class DeviceHubRegisters(SchemaBase):
    """Параметры и телеметрия always-on хаба устройств."""

    # --- Конфигурация ---
    registry_path: Annotated[
        str,
        FieldMeta("Путь к реестру", info="YAML-файл реестра устройств (отн. от корня проекта)"),
    ] = "data/devices.yaml"

    supervisor_interval_s: Annotated[
        float,
        FieldMeta(
            "Интервал супервизора",
            info="Период проверки очереди connect/disconnect",
            unit="s",
            min=0.05,
            max=5.0,
        ),
    ] = 0.2

    # --- Телеметрия (readonly) ---
    devices_total: Annotated[int, FieldMeta("Устройств всего", readonly=True)] = 0
    devices_connected: Annotated[int, FieldMeta("Подключено", readonly=True)] = 0
    commands_ok: Annotated[int, FieldMeta("Команд OK", readonly=True)] = 0
    commands_err: Annotated[int, FieldMeta("Команд ERR", readonly=True)] = 0
    last_error: Annotated[str, FieldMeta("Последняя ошибка", readonly=True)] = ""
