"""WordLayoutRegisters — параметры раскладки слова (живые, выносятся в пульт-дашборд).

Координаты первого/последнего диска — в реальных мм робота (как углы листа в
robot_scale). Калибровка угла (zero/invert) подбирается на железе. Readonly-поля —
прогресс раскладки для инспектора/дашборда.
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("WordLayoutRegistersV1")
class WordLayoutRegisters(SchemaBase):
    """Параметры планировщика раскладки слова + readonly-прогресс."""

    # --- Слово ---
    target_word: Annotated[
        str,
        FieldMeta("Слово", info="целевое слово; пробел = разрыв между словами на той же линии"),
    ] = ""
    word_source: Annotated[
        str,
        FieldMeta("Ключ слова в item", info="входной порт со словом (приоритет над «Слово»); пусто = только «Слово»"),
    ] = "word"

    # --- Линия раскладки ---
    # use_pitch=True: от ПЕРВОГО диска по направлению + фиксированному шагу (слово любой
    # длины с одним шагом). use_pitch=False: равномерно между first и last.
    use_pitch: Annotated[
        bool, FieldMeta("Шаг от первого диска", info="True = первый+направление+шаг; False = между first/last")
    ] = True
    first_x: Annotated[float, FieldMeta("Первый диск X (мм)", min=-2000.0, max=2000.0)] = 0.0
    first_y: Annotated[float, FieldMeta("Первый диск Y (мм)", min=-2000.0, max=2000.0)] = 0.0
    line_angle_deg: Annotated[
        float,
        FieldMeta("Направление линии (°)", info="0=вдоль +X, 90=вдоль +Y (X пост.)", min=-360.0, max=360.0),
    ] = 90.0
    pitch_mm: Annotated[
        float,
        FieldMeta("Шаг центров (мм)", info="между центрами; 0 = авто = диаметр (2·радиус)", min=0.0, max=2000.0),
    ] = 0.0
    last_x: Annotated[float, FieldMeta("Последний диск X (мм)", info="режим between", min=-2000.0, max=2000.0)] = 200.0
    last_y: Annotated[float, FieldMeta("Последний диск Y (мм)", info="режим between", min=-2000.0, max=2000.0)] = 0.0

    place_z_mm: Annotated[
        float, FieldMeta("Высота укладки Z (мм)", info="Z в команде роботу (x,y,z,r)", min=-2000.0, max=2000.0)
    ] = 0.0
    disk_radius_mm: Annotated[
        float, FieldMeta("Радиус диска (мм)", info="авто-шаг = диаметр; проверка зазора", min=1.0, max=1000.0)
    ] = 55.0
    word_gap_slots: Annotated[int, FieldMeta("Зазор между словами", info="пустых ячеек на пробел", min=0, max=10)] = 1

    # --- Калибровка угла модель↔робот ---
    angle_zero_deg: Annotated[
        float, FieldMeta("Ноль угла (°)", info="смещение нуля доворота модель↔робот", min=-360.0, max=360.0)
    ] = 0.0
    angle_invert: Annotated[bool, FieldMeta("Инвертировать угол", info="сменить направление доворота (знак)")] = False

    # --- Детект нового диска ---
    predictions_source: Annotated[
        str, FieldMeta("Ключ предсказаний", info="список dict от ml_inference (label/angle_deg/angle_valid)")
    ] = "predictions"
    min_confidence: Annotated[
        float, FieldMeta("Порог уверенности", info="ниже — диск игнорируется", min=0.0, max=1.0)
    ] = 0.5
    settle_frames: Annotated[
        int,
        FieldMeta(
            "Кадров стабильности",
            info="кадров подряд буква держится → берём (1 для тракта «1 кадр на диск»)",
            min=1,
            max=120,
        ),
    ] = 1
    use_trigger: Annotated[
        bool, FieldMeta("Брать по триггеру", info="брать диск только по сигналу trigger (иначе авто по стабильности)")
    ] = False
    trigger_source: Annotated[str, FieldMeta("Ключ триггера", info="входной порт сигнала «взять диск»")] = "trigger"

    # --- Забор (калибровка) ---
    # Координата забора диска с ленты приходит из узла pixel_to_robot ({x_mm,y_mm} в мм
    # робота) + опц. энкодер кадра. Слот слова — это УКЛАДКА (place), забор — это pick.
    pick_source: Annotated[str, FieldMeta("Ключ забора", info="{x_mm,y_mm} позиции забора от pixel_to_robot")] = (
        "pick_xy"
    )
    encoder_source: Annotated[
        str, FieldMeta("Ключ энкодера", info="e_capture (энкодер кадра) от pixel_to_robot — для CVT-трекинга")
    ] = "e_capture"
    require_pick: Annotated[
        bool,
        FieldMeta(
            "Требовать забор",
            info="True: без калибровки (нет pick) диск не кладём, слот не съедаем (прод-безопасно); "
            "False: раскладка идёт без робота (демо)",
        ),
    ] = True

    # --- Выход ---
    job_key: Annotated[
        str,
        FieldMeta("Ключ задания", info="ключ позы {pick_*, place_*, e_capture} (вяжется к robot_io.job_source)"),
    ] = "robot_job"

    # --- Возврат на ленту ---
    # По сигналу с пульта (свободная кнопка телефона) робот возвращает ВСЕ выложенные буквы
    # обратно на конвейер, затем раскладка сбрасывается (можно вводить новое слово).
    return_trigger_source: Annotated[
        str,
        FieldMeta("Ключ сигнала возврата", info="входной порт сигнала «вернуть на ленту» (имя ИСХОДНОГО порта)"),
    ] = "signal_1"
    return_jobs_key: Annotated[
        str,
        FieldMeta("Ключ заданий возврата", info="список поз возврата (вяжется к robot_io.return_jobs_source)"),
    ] = "robot_return_jobs"

    # --- Readonly: прогресс ---
    word_norm: Annotated[str, FieldMeta("Слово (норм.)", readonly=True)] = ""
    slots_total: Annotated[int, FieldMeta("Слотов всего", readonly=True)] = 0
    slots_filled: Annotated[int, FieldMeta("Заполнено", readonly=True)] = 0
    next_letter: Annotated[str, FieldMeta("Следующая буква", readonly=True)] = ""
    last_label: Annotated[str, FieldMeta("Последняя буква", readonly=True)] = ""
    last_angle_deg: Annotated[float, FieldMeta("Угол модели (°)", readonly=True)] = 0.0
    last_correction_deg: Annotated[float, FieldMeta("Доворот (°)", readonly=True)] = 0.0
    jobs_emitted: Annotated[int, FieldMeta("Заданий выдано", readonly=True)] = 0
    done: Annotated[bool, FieldMeta("Слово готово", readonly=True)] = False
    spacing_warn: Annotated[bool, FieldMeta("Слоты теснее диаметра", readonly=True)] = False
