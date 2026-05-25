"""Привязка реестра дисплеев к SystemBlueprint (ADR-025 config-driven memory).

Чистые функции для формирования декларативного описания SHM-сегментов
дисплеев в blueprint dict. Каждый зарегистрированный дисплей превращается
в запись ``processes.ui_process.memory.display_<id>``.

Важно:
    Фактическое создание SHM-сегмента происходит при следующем запуске
    ``ProcessManagerProcess`` через ``SharedResourcesManager``. Эти функции
    **только формируют декларативное описание** в blueprint — никакой
    аллокации памяти, IPC или side-effects здесь нет.

Слой:
    Это **prototype-обёртка** (не framework). ``display_module`` намеренно
    generic и не знает про ``ui_process``. Привязка конкретного процесса
    к реестру — ответственность прикладного слоя.
"""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiprocess_framework.modules.display_module import DisplayRegistry

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# Маппинг формата пикселей → количество каналов
# -----------------------------------------------------------------------

_FORMAT_CHANNELS: dict[str, int] = {
    "BGR": 3,
    "RGB": 3,
    "GRAY": 1,
    "RGBA": 4,
}


def _format_to_channels(fmt: str) -> int:
    """Преобразовать строковый формат пикселей в количество каналов.

    Args:
        fmt: Формат пикселей (``"BGR"``, ``"RGB"``, ``"GRAY"``, ``"RGBA"``).

    Returns:
        Количество каналов изображения. Для неизвестного формата
        возвращает 3 (fallback) и логирует предупреждение.
    """
    channels = _FORMAT_CHANNELS.get(fmt)
    if channels is not None:
        return channels

    logger.warning(
        "Неизвестный формат пикселей '%s' — используется fallback 3 канала (BGR)",
        fmt,
    )
    return 3


# -----------------------------------------------------------------------
# Публичные функции
# -----------------------------------------------------------------------


def bind_displays_to_blueprint(
    registry: DisplayRegistry,
    blueprint: dict,
) -> dict:
    """Записать SHM-описания дисплеев из реестра в blueprint dict.

    Для каждого ``DisplayEntry`` из ``registry.list()`` добавляет в
    ``blueprint["processes"]["ui_process"]["memory"]`` запись
    ``"display_<entry.id>"`` вида::

        {
            "blocks": entry.ring_buffer_blocks,
            "frame_shape": [entry.height, entry.width, channels]
        }

    Фактическое создание SHM-сегмента происходит при следующем запуске
    ``ProcessManagerProcess`` через ``SharedResourcesManager``. Эта
    функция **только формирует декларативное описание** в blueprint.

    Args:
        registry: Реестр дисплеев (framework ``DisplayRegistry``).
        blueprint: Blueprint dict (результат ``SystemBlueprint.model_dump()``
            или сырой dict). **Не мутируется** — возвращается новая копия.

    Returns:
        Новый dict с добавленными записями ``display_<id>`` в секции
        ``processes.ui_process.memory``. Если реестр пуст — возвращается
        эквивалентная копия без добавления пустых секций.
    """
    entries = registry.list()

    # Пустой реестр — возвращаем копию без лишних секций
    if not entries:
        return copy.deepcopy(blueprint)

    result = copy.deepcopy(blueprint)

    # Обеспечиваем наличие пути processes.ui_process.memory
    if "processes" not in result:
        logger.warning("Blueprint не содержит секции 'processes' — создана минимальная структура для ui_process")
        result["processes"] = {}

    processes = result["processes"]

    if "ui_process" not in processes:
        logger.warning(
            "Blueprint не содержит секции 'ui_process' в 'processes' — создана минимальная структура {'memory': {}}"
        )
        processes["ui_process"] = {"memory": {}}

    ui_process = processes["ui_process"]

    if "memory" not in ui_process:
        ui_process["memory"] = {}

    memory = ui_process["memory"]

    # Записываем SHM-описание каждого дисплея
    for entry in entries:
        key = f"display_{entry.id}"
        channels = _format_to_channels(entry.format)
        memory[key] = {
            "blocks": entry.ring_buffer_blocks,
            "frame_shape": [entry.height, entry.width, channels],
        }
        logger.debug(
            "Blueprint: добавлен SHM-сегмент '%s' — blocks=%d, frame_shape=%s",
            key,
            entry.ring_buffer_blocks,
            [entry.height, entry.width, channels],
        )

    return result


def cleanup_display_from_blueprint(
    display_id: str,
    blueprint: dict,
) -> dict:
    """Удалить SHM-описание дисплея из blueprint dict.

    Удаляет ключ ``"display_<display_id>"`` из
    ``blueprint["processes"]["ui_process"]["memory"]`` если он существует.

    Фактическое освобождение SHM-сегмента происходит при следующем
    рестарте ``ProcessManagerProcess`` (ADR-025). Эта функция **только
    удаляет декларативное описание** из blueprint.

    Args:
        display_id: Идентификатор дисплея (без префикса ``"display_"``).
        blueprint: Blueprint dict. **Не мутируется** — возвращается
            новая копия.

    Returns:
        Новый dict без записи ``display_<display_id>`` в секции
        ``processes.ui_process.memory``. Если ключа не было —
        возвращается эквивалентная копия без изменений.
    """
    result = copy.deepcopy(blueprint)

    key = f"display_{display_id}"

    try:
        memory = result["processes"]["ui_process"]["memory"]
    except (KeyError, TypeError):
        # Нет пути processes.ui_process.memory — нечего удалять
        return result

    # Тихое удаление (pop без исключения если ключа нет)
    memory.pop(key, None)

    return result
