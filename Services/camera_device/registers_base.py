# -*- coding: utf-8 -*-
"""Register ядра камеры (Task 2.3a): общий для базового плагина с `driver: fake` и вендорских плагинов.

Поля делятся на: идентичность прибора (`device_select` + `device_*`), цикл сеанса (`timeout_ms`, `watchdog_s`),
профиль run (`trigger_*`, `exposure_time`), профиль rest (`rest_*`) и телеметрию (`device_state`, `frames`).
План записи строят `params.build_plan` по этим полям и таблице привязки драйвера (`bindings()` плагина).
`param_errors` здесь нет: писать его некому до Task 2.3b. Пауза перезапуска — `restart_policy.backoff_sec`
процесса в рецепте, не поле register'а.
Слой: Services -> framework, без импорта `multiprocess_prototype`.
"""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("CameraDeviceRegistersV1")
class CameraDeviceRegisters(SchemaBase):
    """Параметры источника кадров и его телеметрия."""

    driver: Annotated[
        str,
        FieldMeta("Драйвер", info="Имя драйвера порта; сейчас известен только fake"),
    ] = "fake"

    camera_id: Annotated[
        int,
        FieldMeta("ID камеры", info="Попадает в item (camera_id) — различать несколько источников", min=0),
    ] = 0

    # --- Идентичность прибора (Р1, Р3): какое поле читать, решает device_select ---
    device_select: Annotated[
        Literal["serial", "ip", "url", "index", "first"],
        FieldMeta(
            "Выбор прибора",
            info="Как найти прибор; first — первый из перечисленных, только явно (порядок не обещан)",
        ),
    ] = "serial"

    device_serial: Annotated[str, FieldMeta("Серийный номер", info="Для device_select=serial")] = ""
    device_ip: Annotated[str, FieldMeta("IP-адрес", info="Для device_select=ip")] = ""
    device_url: Annotated[str, FieldMeta("URL", info="Для device_select=url")] = ""
    device_index: Annotated[int, FieldMeta("Индекс прибора", info="Для device_select=index", min=0)] = 0
    device_name: Annotated[
        str, FieldMeta("Имя прибора", info="Для device_select=index: сверка имени, порядок перечисления не обещан")
    ] = ""

    auto_start: Annotated[
        bool,
        FieldMeta("Автозахват", info="Взять прибор при старте процесса; иначе — командой take_device"),
    ] = True

    # --- Цикл сеанса: замораживаются при создании сеанса, правка — перезапуск процесса ---
    timeout_ms: Annotated[
        int,
        FieldMeta("Таймаут кадра, мс", info="Ожидание кадра у порта; правка — перезапуск процесса", min=1),
    ] = 500

    watchdog_s: Annotated[
        float,
        FieldMeta("Сторож, с", info="Срок зависания вызова порта; должен быть больше таймаута кадра"),
    ] = 5.0

    # --- Профиль run: группа триггера, затем экспозиция (порядок объявления = порядок записи) ---
    trigger_managed: Annotated[
        bool,
        FieldMeta(
            "Управлять триггером", info="Выкл — узлы триггера прибора не трогаются", apply="restart", ui_group="trigger"
        ),
    ] = False

    trigger_mode: Annotated[
        Literal["Off", "On"],
        FieldMeta(
            "Режим триггера",
            apply="restart",
            ui_group="trigger",
            enabled_if={"trigger_managed": [True]},
        ),
    ] = "Off"

    trigger_source: Annotated[
        Literal["Line0", "Software", "SelfTrigger"],
        FieldMeta(
            "Источник триггера",
            apply="restart",
            ui_group="trigger",
            enabled_if={"trigger_managed": [True], "trigger_mode": ["On"]},
        ),
    ] = "Line0"

    trigger_period_ms: Annotated[
        int,
        FieldMeta(
            "Период самотриггера, мс",
            apply="restart",
            ui_group="trigger",
            enabled_if={"trigger_managed": [True], "trigger_source": ["SelfTrigger"]},
        ),
    ] = 40

    exposure_time: Annotated[
        float,
        FieldMeta("Экспозиция, мкс", info="Пишется в прибор при каждом take_device", apply="live"),
    ] = 10000.0

    # --- Профиль rest: что записать в прибор после остановки захвата (значения, привязок у них нет) ---
    rest_managed: Annotated[
        bool,
        FieldMeta("Управлять покоем", info="Вкл — после release_device записать триггер покоя", ui_group="rest"),
    ] = False

    rest_trigger_mode: Annotated[
        Literal["Off", "On"],
        FieldMeta("Режим триггера в покое", ui_group="rest", enabled_if={"rest_managed": [True]}),
    ] = "On"

    rest_trigger_source: Annotated[
        Literal["Line0", "Software", "SelfTrigger"],
        FieldMeta("Источник триггера в покое", ui_group="rest", enabled_if={"rest_managed": [True]}),
    ] = "Line0"

    # --- Телеметрия (readonly — GUI смотрит, не правит) ---
    device_state: Annotated[
        str,
        FieldMeta(
            "Состояние прибора",
            info="idle | opening | grabbing | stopping | closed | busy | not_found | error",
            readonly=True,
        ),
    ] = "closed"

    frames: Annotated[
        int,
        FieldMeta("Кадров", info="Сколько кадров отдано с момента старта", readonly=True),
    ] = 0
