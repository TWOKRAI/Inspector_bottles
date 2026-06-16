"""PixelToRobotRegisters — параметры узла применения калибровки камера↔робот.

Узел грузит гомографию из ``config/calibration/<camera_id>.yaml`` (артефакт визарда
camera_robot_calibration) и переводит пиксельный центр диска в координаты робота (мм) —
позицию ЗАБОРА с ленты. Readonly-поля — диагностика для инспектора/дашборда.

Энкодер для CVT-трекинга узел НЕ читает (чтобы не стучать по Modbus): его читает один
раз на задание драйвер в enqueue_job (девайс-сторона, минимум обращений к роботу).
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("PixelToRobotRegistersV1")
class PixelToRobotRegisters(SchemaBase):
    """Параметры применения гомографии px→мм + readonly-диагностика."""

    # --- Источник калибровки ---
    camera_id: Annotated[str, FieldMeta("ID камеры", info="файл калибровки config/calibration/<camera_id>.yaml")] = (
        "cam0"
    )
    calibration_dir: Annotated[str, FieldMeta("Папка калибровок", info="база, где лежит <camera_id>.yaml")] = (
        "config/calibration"
    )

    # --- Вход / выход ---
    center_key: Annotated[
        str,
        FieldMeta("Ключ центра px", info="ищется в item['sidecar'][key], затем item[key]; [x,y] в px ROI"),
    ] = "center_px"
    output_key: Annotated[
        str, FieldMeta("Ключ забора", info="куда писать {x_mm,y_mm} позиции забора (вяжется к word_layout.pick_xy)")
    ] = "pick_xy"

    # --- Согласование систем координат px ---
    # Гомография ROI-локальна (фитилась по детекциям в том же ROI). Если детектор узла и
    # калибровки работают в РАЗНЫХ ROI — здесь сдвиг (px центра + offset → система калибровки).
    roi_offset_x: Annotated[
        int, FieldMeta("Сдвиг X (px)", info="прибавить к px перед гомографией (0 = тот же ROI)", min=-10000, max=10000)
    ] = 0
    roi_offset_y: Annotated[
        int, FieldMeta("Сдвиг Y (px)", info="прибавить к px перед гомографией (0 = тот же ROI)", min=-10000, max=10000)
    ] = 0

    # --- Readonly: диагностика ---
    loaded: Annotated[bool, FieldMeta("Калибровка загружена", readonly=True)] = False
    last_x_mm: Annotated[float, FieldMeta("Последний X (мм)", readonly=True)] = 0.0
    last_y_mm: Annotated[float, FieldMeta("Последний Y (мм)", readonly=True)] = 0.0
    conversions: Annotated[int, FieldMeta("Переводов выполнено", readonly=True)] = 0
    last_error: Annotated[str, FieldMeta("Последняя ошибка", readonly=True)] = ""
