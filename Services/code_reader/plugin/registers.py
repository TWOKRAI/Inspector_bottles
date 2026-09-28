# -*- coding: utf-8 -*-
"""CodeReaderRegisters — параметры приёма и телеметрия считывателя.

V3_MY_PURE, как в `Services/modbus/plugin/registers.py`: register — единый
источник параметров, плагин всегда читает `self._reg`. Часть полей readonly —
это то, что GUI показывает вживую (состояние связи, последний код, счётчики).

Значения по умолчанию сняты с нашего экземпляра `MV-ID3013PM-06M-SENSOTEC`
(прошивка `V4.0.2.C 251201`), а не взяты из мануала — см. `docs/SETUP.md`.
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("CodeReaderRegistersV1")
class CodeReaderRegisters(SchemaBase):
    """Параметры приёма результатов чтения и телеметрия связи."""

    # --- Приём (прибор в режиме TCP Client подключается к нам) ---
    host: Annotated[
        str,
        FieldMeta("Интерфейс", info="0.0.0.0 = слушать на всех интерфейсах"),
    ] = "0.0.0.0"  # nosec B104 — приём с прибора по локальной сети линии

    port: Annotated[
        int,
        FieldMeta("Порт приёма", info="`TCP Client Port` в IDMVS", min=1, max=65535),
    ] = 5000

    reader_id: Annotated[
        str,
        FieldMeta("ID считывателя", info="Попадает в item — различать несколько приборов"),
    ] = "id3013"

    auto_start: Annotated[
        bool,
        FieldMeta("Автоприём", info="Поднять приём при старте процесса"),
    ] = True

    # --- Формат пакета (настройки прибора, см. docs/SETUP.md разд. 4-5) ---
    terminator: Annotated[
        str,
        FieldMeta(
            "Терминатор",
            info="`Output Stop Text` прибора; пустое значение приём отвергает (ADR-CR-005)",
        ),
    ] = ";"

    prefix: Annotated[
        str,
        FieldMeta("Префикс", info="`Output Start Text`; пусто, если не задан"),
    ] = ""

    no_code_text: Annotated[
        str,
        FieldMeta("Текст «кода нет»", info="`Output NoRead Text`"),
    ] = "NoRead"

    bad_code_text: Annotated[
        str,
        FieldMeta(
            "Текст «код есть, не читается»",
            info="`Output With Code NoRead Text`; пусто = различение выключено",
        ),
    ] = ""

    # --- Телеметрия (readonly — GUI смотрит, не правит) ---
    sink_state: Annotated[
        str,
        FieldMeta("Состояние приёма", info="stopped | listening | connected", readonly=True),
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
        FieldMeta(
            "Прочитано кодов",
            info="Только успешные чтения. Всего срабатываний = total_reads + no_reads + bad_reads",
            readonly=True,
        ),
    ] = 0

    no_reads: Annotated[
        int,
        FieldMeta("Пустых срабатываний", info="Кода в кадре не нашлось", readonly=True),
    ] = 0

    bad_reads: Annotated[
        int,
        FieldMeta("Код есть, не читается", readonly=True),
    ] = 0

    dropped: Annotated[
        int,
        FieldMeta("Потеряно из очереди", info="Приём быстрее, чем pipeline забирает", readonly=True),
    ] = 0

    last_error: Annotated[
        str,
        FieldMeta("Последняя ошибка", readonly=True),
    ] = ""
