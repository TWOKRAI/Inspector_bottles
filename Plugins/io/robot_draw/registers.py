"""RobotDrawRegisters — приёмник точек рисования в pipeline (live-tunable)."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("RobotDrawRegistersV1")
class RobotDrawRegisters(SchemaBase):
    """Параметры и счётчики форвардера точек рисования robot_draw."""

    # --- Привязка к устройству в реестре hub ---
    device_id: Annotated[str, FieldMeta("ID устройства", info="id робота в реестре devices")] = "robot_main"

    # --- Ключ задания в item и таймаут IPC ---
    points_source: Annotated[str, FieldMeta("Ключ точек в item", info="list[{x_mm,y_mm,pen}] → очередь форварда")] = (
        "draw_points"
    )
    # Pipeline-триггер «Рисовать»: если задан, robot_draw взводится (как кнопка
    # «Отправить роботу»), когда в item приходит truthy под этим ключом. Ключ = имя
    # ИСХОДНОГО порта провода (без переименования), напр. сигнал пульта out_1.
    # Пусто = триггер из pipeline выключен (только команда robot_draw_send). Универсально:
    # любой контрол пульта вяжется к роботу в графе + trigger_source — без правок кода.
    trigger_source: Annotated[
        str,
        FieldMeta("Ключ триггера в item", info="сигнал из pipeline взводит рисование (напр. out_1); пусто = выкл"),
    ] = ""
    request_timeout_s: Annotated[
        float,
        FieldMeta("Таймаут IPC (с)", info="enqueue в hub мгновенный; рисование идёт асинхронно", min=0.5, max=60.0),
    ] = 5.0

    # --- Пробный прогон (предпросмотр точек перед боем) ---
    # True = «Рисовать» пишет точки в текст (dump_path) и роботу НЕ отправляет —
    # можно убедиться, что координаты в рабочей зоне и путь корректен. False = шлём роботу.
    dry_run: Annotated[
        bool,
        FieldMeta("Пробный прогон (без робота)", info="True = точки в текст, роботу не слать (проверка)"),
    ] = False
    dump_path: Annotated[
        str,
        FieldMeta("Файл предпросмотра", info="куда писать точки при пробном прогоне (мм + перо + проходы)"),
    ] = "data/robot_points_preview.txt"

    # --- Счётчики (readonly) ---
    jobs_sent: Annotated[int, FieldMeta("Заданий отправлено", readonly=True)] = 0
    jobs_dropped: Annotated[int, FieldMeta("Заданий отброшено", readonly=True)] = 0
    points_total: Annotated[int, FieldMeta("Точек всего", readonly=True)] = 0
    hub_errors: Annotated[int, FieldMeta("Ошибок hub", readonly=True)] = 0
    queue_len: Annotated[int, FieldMeta("В очереди", readonly=True)] = 0
    last_error: Annotated[str, FieldMeta("Последняя ошибка", readonly=True)] = ""
