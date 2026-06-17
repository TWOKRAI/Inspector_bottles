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

    # --- Линейная калибровка (альтернатива файлу гомографии) ---
    use_linear: Annotated[
        bool,
        FieldMeta(
            "Линейная калибровка (без файла)",
            info="True = билинейная интерполяция 4 углов; False = гомография",
        ),
    ] = False

    # Размер ROI в пикселях — база маппинга.  Должны совпадать с roi_crop.width/height
    # активного рецепта.  guard: max(1, значение) применяется в geometry.
    lin_src_width: Annotated[
        int,
        FieldMeta(
            "Ширина ROI (px)",
            info="кадр-источник билинейной нормировки (roi_crop.width)",
            min=1,
            max=10000,
        ),
    ] = 800
    lin_src_height: Annotated[
        int,
        FieldMeta(
            "Высота ROI (px)",
            info="кадр-источник билинейной нормировки (roi_crop.height)",
            min=1,
            max=10000,
        ),
    ] = 481

    # 4 угла ROI в координатах робота (мм).  Порядок: TL(0,0) → TR(W,0) → BR(W,H) → BL(0,H).
    # Дефолты — невырожденный плейсхолдер (прямоугольник рабочей зоны); владелец перепишет
    # своими замерами через инспектор или рецепт.
    lin_tl_x: Annotated[float, FieldMeta("TL X (мм)", info="верх-лево ROI px(0,0) → X робота")] = 200.0
    lin_tl_y: Annotated[float, FieldMeta("TL Y (мм)", info="верх-лево ROI px(0,0) → Y робота")] = -300.0
    lin_tr_x: Annotated[float, FieldMeta("TR X (мм)", info="верх-право ROI px(W,0) → X робота")] = 400.0
    lin_tr_y: Annotated[float, FieldMeta("TR Y (мм)", info="верх-право ROI px(W,0) → Y робота")] = -300.0
    lin_br_x: Annotated[float, FieldMeta("BR X (мм)", info="низ-право ROI px(W,H) → X робота")] = 400.0
    lin_br_y: Annotated[float, FieldMeta("BR Y (мм)", info="низ-право ROI px(W,H) → Y робота")] = -100.0
    lin_bl_x: Annotated[float, FieldMeta("BL X (мм)", info="низ-лево ROI px(0,H) → X робота")] = 200.0
    lin_bl_y: Annotated[float, FieldMeta("BL Y (мм)", info="низ-лево ROI px(0,H) → Y робота")] = -100.0

    # --- Readonly: диагностика ---
    loaded: Annotated[bool, FieldMeta("Калибровка загружена", readonly=True)] = False
    last_x_mm: Annotated[float, FieldMeta("Последний X (мм)", readonly=True)] = 0.0
    last_y_mm: Annotated[float, FieldMeta("Последний Y (мм)", readonly=True)] = 0.0
    conversions: Annotated[int, FieldMeta("Переводов выполнено", readonly=True)] = 0
    last_error: Annotated[str, FieldMeta("Последняя ошибка", readonly=True)] = ""
