"""process_tree_config — конфигурация EntityTreeWidget для вкладки «Процессы».

Определяет структуру дерева процессов/воркеров:
- Parent level: процессы (class_path, priority, pid, auto_start, alive)
- Child level: воркеры (worker_type, target_interval_ms, cycle_duration_ms, ...)
"""
from __future__ import annotations

from multiprocess_prototype.frontend.widgets.base.editor.entity_tree_config import (
    EntityLevel,
    EntityTreeConfig,
    ParamDef,
)


def _format_class_path(value: object) -> str:
    """Отформатировать class_path — показать только короткое имя класса.

    Args:
        value: Полный путь класса (строка).

    Returns:
        Короткое имя класса (после последней точки).
    """
    if not isinstance(value, str) or not value:
        return "—"
    return value.rsplit(".", 1)[-1]


def _format_cycle_ms(value: object) -> str:
    """Отформатировать время цикла в миллисекундах.

    Args:
        value: Время цикла (число).

    Returns:
        Строка вида «123.4 мс».
    """
    if isinstance(value, (int, float)):
        return f"{value:.1f} мс"
    return str(value)


def _format_hz(value: object) -> str:
    """Отформатировать частоту в герцах.

    Args:
        value: Частота (число).

    Returns:
        Строка вида «7.7 Hz».
    """
    if isinstance(value, (int, float)):
        return f"{value:.1f} Hz"
    return str(value)


def _format_interval_ms(value: object) -> str:
    """Отформатировать целевой интервал в миллисекундах.

    Args:
        value: Интервал (число).

    Returns:
        Строка вида «100 мс».
    """
    if isinstance(value, (int, float)):
        return f"{int(value)} мс"
    return str(value)


def _process_summary(data: dict) -> str:
    """Построить строку сводки процесса.

    Формат: «КлассКороткий | приоритет»

    Args:
        data: Данные процесса (dict).

    Returns:
        Строка сводки.
    """
    class_path = data.get("class_path", "")
    short_class = class_path.rsplit(".", 1)[-1] if class_path else "—"
    priority = data.get("priority", "—") or "—"
    return f"{short_class} | {priority}"


def _worker_summary(data: dict) -> str:
    """Построить строку сводки воркера.

    Формат: «130ms / 7.7Hz» или «—» если нет timing данных.

    Args:
        data: Данные воркера (dict).

    Returns:
        Строка сводки.
    """
    cycle_ms = data.get("cycle_duration_ms")
    eff_hz = data.get("effective_hz")
    if cycle_ms is not None and eff_hz is not None:
        return f"{cycle_ms:.0f}ms / {eff_hz:.1f}Hz"
    if cycle_ms is not None:
        return f"{cycle_ms:.0f}ms"
    if eff_hz is not None:
        return f"{eff_hz:.1f}Hz"
    return "—"


# --- Конфигурация дерева процессов ---

PROCESS_TREE_CONFIG = EntityTreeConfig(
    columns=["Элемент", "Значение", "Комментарий", "Сводка"],
    parent_level=EntityLevel(
        name="process",
        role_key="process",
        icon="■",
        bold=True,
        params=[
            ParamDef("class_path", "Класс", "Класс процесса", formatter=_format_class_path),
            ParamDef("priority", "Приоритет", "low / normal / high / urgent"),
            ParamDef("pid", "PID", "ID процесса"),
            ParamDef("auto_start", "Автозапуск", "Запуск при старте системы", is_bool=True),
            ParamDef("alive", "Alive", "Процесс жив", is_bool=True),
        ],
        summary_builder=_process_summary,
    ),
    child_level=EntityLevel(
        name="worker",
        role_key="worker",
        icon="□",
        bold=False,
        params=[
            ParamDef("worker_type", "Тип", "Тип воркера"),
            ParamDef("target_interval_ms", "Интервал", "Целевой интервал цикла, мс",
                     formatter=_format_interval_ms),
            ParamDef("cycle_duration_ms", "Цикл", "Фактическое время цикла, мс",
                     formatter=_format_cycle_ms),
            ParamDef("effective_hz", "Частота", "Эффективная частота",
                     formatter=_format_hz),
            ParamDef("sleep_ms", "Задержка", "Smart sleep, мс",
                     formatter=_format_cycle_ms),
            ParamDef("restart_count", "Рестарты", "Количество рестартов"),
        ],
        summary_builder=_worker_summary,
    ),
    column_widths=[220, 140, 160, 280],
)


__all__ = ["PROCESS_TREE_CONFIG"]
