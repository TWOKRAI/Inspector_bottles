"""FrameSaverRegisters — все параметры frame_saver плагина.

V3_MY_PURE: register = единый источник параметров + FieldMeta.
Plugin всегда работает через self._reg (managed или локальный).

Фаза 0 (сохранение изображений на диск): настраиваемое имя файла, организация
по дате (папка дня), resume нумерации с диска, retention по дням, расширенный
набор форматов и два режима сохранения (поток / по триггеру).
"""

from __future__ import annotations

from typing import Annotated
from typing import Literal

from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import FieldMeta
from multiprocess_framework.modules.process_module.plugins import SchemaBase


@register_schema("FrameSaverRegistersV1")
class FrameSaverRegisters(SchemaBase):
    """Все параметры frame_saver — путь, имя файла, дата, retention, формат, режим."""

    # --- Путь и имя файла ---
    output_dir: Annotated[
        str,
        FieldMeta(
            "Output Dir",
            info="Базовая директория для сохранённых кадров",
        ),
    ] = "data/frames"

    filename_prefix: Annotated[
        str,
        FieldMeta(
            "Filename Prefix",
            info="Базовое имя файла (префикс перед индексом)",
        ),
    ] = "frame"

    index_source: Annotated[
        Literal["counter", "frame_id"],
        FieldMeta(
            "Index Source",
            info="counter — сквозная нумерация с resume с диска; frame_id — индекс из данных кадра",
        ),
    ] = "counter"

    index_padding: Annotated[
        int,
        FieldMeta(
            "Index Padding",
            info="Ширина нуль-заполнения индекса в имени файла",
            min=1,
            max=12,
        ),
    ] = 6

    # --- Организация по дате ---
    subfolder_by_date: Annotated[
        bool,
        FieldMeta(
            "Subfolder By Date",
            info="Сохранять в подпапку output_dir/<YYYY-MM-DD>/ (папка дня)",
        ),
    ] = True

    # --- Retention (ограничение роста диска) ---
    max_days: Annotated[
        int,
        FieldMeta(
            "Max Days",
            info="Хранить N последних дней (папок); 0 = без лимита. Старые папки-даты удаляются",
            min=0,
            unit="дн",
        ),
    ] = 7

    # --- Формат ---
    image_format: Annotated[
        Literal["jpeg", "png", "bmp", "tiff", "webp"],
        FieldMeta(
            "Image Format",
            info="Формат сохранения изображения",
        ),
    ] = "jpeg"

    jpeg_quality: Annotated[
        int,
        FieldMeta(
            "JPEG Quality",
            info="Качество для jpeg/webp (1-100)",
            min=1,
            max=100,
        ),
    ] = 85

    # --- Режим сохранения ---
    save_mode: Annotated[
        Literal["stream", "trigger"],
        FieldMeta(
            "Save Mode",
            info="stream — поток (каждый N-й кадр); trigger — только по команде save_now",
        ),
    ] = "stream"

    save_every_n: Annotated[
        int,
        FieldMeta(
            "Save Every N",
            info="Для режима stream: сохранять каждый N-й кадр",
            min=1,
        ),
    ] = 1

    # --- Поведение в режиме trigger ---
    buffer_mode: Annotated[
        Literal["last", "accumulate"],
        FieldMeta(
            "Buffer Mode",
            info="last — хранить только последний кадр; accumulate — копить кадры до команды",
        ),
    ] = "last"

    buffer_size: Annotated[
        int,
        FieldMeta(
            "Buffer Size",
            info="Макс. кадров в накоплении (для buffer_mode=accumulate)",
            min=1,
        ),
    ] = 100

    # --- Триггер сохранения (вход True/False) ---
    manual_trigger: Annotated[
        bool,
        FieldMeta(
            "Manual Trigger",
            info="Ручной триггер: переключи в True → сохранить (срабатывает по фронту False→True)",
        ),
    ] = False

    trigger_key: Annotated[
        str,
        FieldMeta(
            "Trigger Key",
            info="Ключ во входном item с булевым сигналом (приходит по проводу со входа trigger)",
        ),
    ] = "trigger"
