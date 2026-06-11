"""RobotIoRegisters — параметры и телеметрия плагина robot_io.

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


@register_schema("RobotIoRegistersV1")
class RobotIoRegisters(SchemaBase):
    """Параметры и телеметрия владельца соединения с роботом (CVT-исполнитель)."""

    # --- Подключение (единственный источник конфига робота в процессе) ---
    host: Annotated[str, FieldMeta("Хост робота", info="IP Modbus-TCP сервера робота")] = "192.168.1.7"
    port: Annotated[int, FieldMeta("Порт", min=1, max=65535)] = 502
    unit_id: Annotated[int, FieldMeta("Unit ID", info="Modbus id робота (u3: 2)", min=0, max=247)] = 2
    timeout_sec: Annotated[
        float, FieldMeta("Таймаут", info="Малый: Lock держится на время I/O", unit="s", min=0.1, max=10.0)
    ] = 1.0
    word_order: Annotated[str, FieldMeta("Порядок слов DW", info="little | big (подбор: CLI cal)")] = "little"
    auto_connect: Annotated[bool, FieldMeta("Автоподключение", info="Подключаться при старте")] = True

    # --- Feeder (фоновая подача заданий) ---
    feed_poll_s: Annotated[
        float, FieldMeta("Период поллинга", info="Опрос is_free в feeder", unit="s", min=0.005, max=1.0)
    ] = 0.03
    accept_wait_s: Annotated[
        float, FieldMeta("Ожидание приёма", info="Таймаут подтверждения задания", unit="s", min=0.1, max=10.0)
    ] = 1.0
    job_wait_s: Annotated[
        float, FieldMeta("Ожидание задания", info="Таймаут исполнения задания", unit="s", min=1.0, max=120.0)
    ] = 20.0
    telemetry_interval_s: Annotated[
        float, FieldMeta("Интервал телеметрии", info="Публикация в state-дерево", unit="s", min=0.1, max=10.0)
    ] = 0.5

    # --- Поведение в pipeline ---
    job_source: Annotated[str, FieldMeta("Ключ задания в item", info="dict {x_mm, y_mm} -> очередь feeder")] = (
        "robot_job"
    )
    manual_mode: Annotated[bool, FieldMeta("Ручной режим", info="Пауза авто-подачи (вкладка/калибровка)")] = False

    # --- Телеметрия (readonly) ---
    conn_state: Annotated[str, FieldMeta("Состояние", readonly=True)] = "disconnected"
    free: Annotated[bool, FieldMeta("Робот свободен", readonly=True)] = False
    mode: Annotated[str, FieldMeta("Режим", readonly=True)] = "cvt"
    encoder: Annotated[int, FieldMeta("Энкодер", readonly=True)] = 0
    queue_len: Annotated[int, FieldMeta("В очереди", readonly=True)] = 0
    jobs_sent: Annotated[int, FieldMeta("Заданий отправлено", readonly=True)] = 0
    jobs_done: Annotated[int, FieldMeta("Заданий выполнено", readonly=True)] = 0
    jobs_failed: Annotated[int, FieldMeta("Заданий с ошибкой", readonly=True)] = 0
    last_error: Annotated[str, FieldMeta("Последняя ошибка", readonly=True)] = ""
