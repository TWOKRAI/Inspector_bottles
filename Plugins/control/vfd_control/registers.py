"""VfdControlRegisters — параметры и телеметрия плагина vfd_control."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("VfdControlRegistersV1")
class VfdControlRegisters(SchemaBase):
    """Параметры и зеркало статуса ПЧ INVT GD20 (мост через робота)."""

    # --- Доменные лимиты ---
    freq_min_hz: Annotated[float, FieldMeta("Мин. частота", unit="Hz", min=0.0, max=400.0)] = 0.0
    freq_max_hz: Annotated[float, FieldMeta("Макс. частота", unit="Hz", min=0.0, max=400.0)] = 50.0
    default_freq_hz: Annotated[float, FieldMeta("Частота по умолчанию", unit="Hz", min=0.0, max=400.0)] = 10.0

    # --- Опрос ---
    poll_interval_s: Annotated[
        float,
        FieldMeta(
            "Интервал опроса",
            info="Пульс VFD_FLAG (зеркало обновляется только по команде)",
            unit="s",
            min=0.1,
            max=10.0,
        ),
    ] = 0.5
    stale_polls_limit: Annotated[
        int, FieldMeta("Лимит замороженных опросов", info="Подряд без роста heartbeat -> мост мёртв", min=2, max=100)
    ] = 5

    # --- Зеркало статуса (readonly) ---
    running: Annotated[bool, FieldMeta("Вращается", readonly=True)] = False
    out_freq_hz: Annotated[float, FieldMeta("Частота на выходе", unit="Hz", readonly=True)] = 0.0
    current_a: Annotated[float, FieldMeta("Ток", unit="A", readonly=True)] = 0.0
    dcbus_v: Annotated[float, FieldMeta("DC-шина", unit="V", readonly=True)] = 0.0
    fault: Annotated[int, FieldMeta("Код аварии", readonly=True)] = 0
    heartbeat: Annotated[int, FieldMeta("Heartbeat моста", readonly=True)] = 0
    comm_errors: Annotated[int, FieldMeta("Ошибок RS-485", info="Смотреть динамику, не абсолют", readonly=True)] = 0
    bridge_alive: Annotated[bool, FieldMeta("Мост жив", readonly=True)] = False
    last_error: Annotated[str, FieldMeta("Последняя ошибка", readonly=True)] = ""
