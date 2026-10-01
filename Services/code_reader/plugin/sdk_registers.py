# -*- coding: utf-8 -*-
"""CodeReaderSdkRegisters — параметры SDK-канала и телеметрия считывателя.

Отдельный register от `CodeReaderRegisters` (TCP): у каналов разные жизненные
циклы (захват прибора через MvCodeReader SDK vs приём порта), общая только форма
item. Часть полей readonly — их GUI показывает вживую.
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("CodeReaderSdkRegistersV1")
class CodeReaderSdkRegisters(SchemaBase):
    """Параметры захвата прибора через SDK и телеметрия."""

    # --- Захват ---
    device_ip: Annotated[
        str,
        FieldMeta("IP прибора", info="Пусто = первый найденный прибор"),
    ] = ""

    reader_id: Annotated[
        str,
        FieldMeta("ID считывателя", info="Попадает в item — различать несколько приборов"),
    ] = "id3013"

    auto_start: Annotated[
        bool,
        FieldMeta("Автозахват", info="Взять прибор при старте процесса; иначе — командой take_device"),
    ] = True

    timeout_ms: Annotated[
        int,
        FieldMeta(
            "Таймаут кадра, мс",
            info="Ожидание кадра в потоке захвата; им же ограничено время остановки",
            # min=10, не 100 из брифа: слепые тесты 6.3 задают timeout_ms 10/20 через конфиг, а
            # register валидирует присваивание (ValidationError на configure). Решение лидера.
            min=10,
            max=5000,
        ),
    ] = 500

    # --- Телеметрия (readonly — GUI смотрит, не правит) ---
    device_state: Annotated[
        str,
        FieldMeta("Состояние прибора", info="stopped | running | not_found | busy | error", readonly=True),
    ] = "stopped"

    last_code: Annotated[
        str,
        FieldMeta("Последний код", readonly=True),
    ] = ""

    last_status: Annotated[
        str,
        FieldMeta("Статус последнего", info="ok | no_code | bad_code", readonly=True),
    ] = ""

    total_reads: Annotated[
        int,
        FieldMeta("Прочитано кодов", info="Кадры с читаемым кодом", readonly=True),
    ] = 0

    no_reads: Annotated[
        int,
        FieldMeta("Пустых срабатываний", info="Кода в кадре не нашлось", readonly=True),
    ] = 0

    bad_reads: Annotated[
        int,
        FieldMeta("Код есть, не читается", readonly=True),
    ] = 0

    frames: Annotated[
        int,
        FieldMeta("Кадров получено", readonly=True),
    ] = 0

    errors: Annotated[
        int,
        FieldMeta("Ошибок", info="Ошибки SDK и декодирования кадра", readonly=True),
    ] = 0

    dropped: Annotated[
        int,
        FieldMeta("Потеряно из очереди", info="Прибор быстрее, чем pipeline забирает", readonly=True),
    ] = 0

    last_error: Annotated[
        str,
        FieldMeta("Последняя ошибка", readonly=True),
    ] = ""
