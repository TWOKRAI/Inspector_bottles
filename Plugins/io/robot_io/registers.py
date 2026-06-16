"""RobotIoRegisters v2 — тонкий job-форвардер в процесс devices.

Соединением теперь владеет DeviceHubPlugin (процесс devices).
robot_io только форвардит job-координаты из pipeline в hub.
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("RobotIoRegistersV2")
class RobotIoRegisters(SchemaBase):
    """Параметры и счётчики тонкого job-форвардера robot_io v2."""

    # --- Привязка к устройству в реестре hub ---
    device_id: Annotated[str, FieldMeta("ID устройства", info="id робота в реестре devices")] = "robot_main"

    # --- Поведение в pipeline ---
    job_source: Annotated[str, FieldMeta("Ключ задания в item", info="dict {x_mm, y_mm} -> очередь forward")] = (
        "robot_job"
    )
    return_jobs_source: Annotated[
        str,
        FieldMeta("Ключ заданий возврата", info="список поз {x_mm,y_mm,z_mm} -> robot_return_job (возврат на ленту)"),
    ] = "robot_return_jobs"
    forward_deque_maxlen: Annotated[
        int, FieldMeta("Макс. очередь", info="Макс. размер forward-deque", min=1, max=1024)
    ] = 64

    # --- Счётчики (readonly) ---
    jobs_forwarded: Annotated[int, FieldMeta("Заданий отправлено", readonly=True)] = 0
    jobs_dropped: Annotated[int, FieldMeta("Заданий отброшено", readonly=True)] = 0
    hub_errors: Annotated[int, FieldMeta("Ошибок hub", readonly=True)] = 0
    last_error: Annotated[str, FieldMeta("Последняя ошибка", readonly=True)] = ""
    queue_len: Annotated[int, FieldMeta("В очереди", readonly=True)] = 0
