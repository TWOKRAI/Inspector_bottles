"""glob_match.py — Glob-style матчинг путей StateStore для GUI-подписок.

Портировано из multiprocess_framework/modules/state_store_module/core/subscription_manager.py
(~30 LOC, алгоритм стабилен — копируем, не импортируем из FW).

Поддерживаемый синтаксис:
  - '*'  — ровно один сегмент пути (любой).
  - '**' — ноль или более сегментов пути (рекурсивно).
  - Литерал — точное совпадение (case-sensitive).
"""
from __future__ import annotations

from functools import lru_cache


# ---------------------------------------------------------------------------
# Кэш разбора паттернов / путей по точке
# ---------------------------------------------------------------------------

@lru_cache(maxsize=256)
def _split_dotted(s: str) -> tuple[str, ...]:
    """Разбивает строку по '.' и кэширует результат.

    Паттернов и путей обычно мало (десятки), а match_glob() может вызываться
    тысячи раз — кэш на split даёт заметный выигрыш.

    Args:
        s: строка вида 'processes.cam.state.fps'.

    Returns:
        Кортеж сегментов ('processes', 'cam', 'state', 'fps').
    """
    if not s:
        return ()
    return tuple(s.split("."))


# ---------------------------------------------------------------------------
# Рекурсивный матчер сегментов
# ---------------------------------------------------------------------------

def _match_segments(
    pattern_segs: tuple[str, ...],
    path_segs: tuple[str, ...],
) -> bool:
    """Рекурсивно проверяет совпадение кортежей сегментов.

    Правила:
      - '*'  — совпадает ровно с одним сегментом.
      - '**' — совпадает с 0, 1, 2, ... N сегментами.
      - Остальные сегменты — точное совпадение (case-sensitive).

    Args:
        pattern_segs: кортеж сегментов паттерна.
        path_segs: кортеж сегментов пути.

    Returns:
        True если паттерн полностью совпадает с путём.
    """
    # Оба пустые — совпадение
    if not pattern_segs and not path_segs:
        return True

    # Паттерн пуст, путь нет — нет совпадения
    if not pattern_segs:
        return False

    head = pattern_segs[0]

    if head == "**":
        # '**' может поглотить 0 сегментов: пропускаем '**'
        if _match_segments(pattern_segs[1:], path_segs):
            return True
        # '**' может поглотить 1+ сегментов: съедаем один сегмент пути
        return bool(path_segs and _match_segments(pattern_segs, path_segs[1:]))

    # Паттерн не пуст, но путь кончился — нет совпадения
    if not path_segs:
        return False

    # '*' — любой один сегмент, или точное совпадение
    if head == "*" or head == path_segs[0]:
        return _match_segments(pattern_segs[1:], path_segs[1:])

    return False


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

def match_glob(pattern: str, path: str) -> bool:
    """Проверить совпадение glob-паттерна с путём StateStore.

    Ведущие/завершающие точки нормализуются (обрезаются).

    Args:
        pattern: glob-паттерн, например 'processes.*.state.fps'.
        path: конкретный путь, например 'processes.cam.state.fps'.

    Returns:
        True если паттерн совпадает с путём.

    Примеры:
        >>> match_glob("processes.cam.state.fps", "processes.cam.state.fps")
        True
        >>> match_glob("processes.*.state.fps", "processes.cam.state.fps")
        True
        >>> match_glob("processes.**", "processes.x.y.z")
        True
        >>> match_glob("processes.cam.config.fps", "processes.cam.state.fps")
        False
    """
    # Нормализация: обрезаем ведущие/завершающие точки
    pattern = pattern.strip(".")
    path = path.strip(".")

    pattern_segs = _split_dotted(pattern)
    path_segs = _split_dotted(path)

    return _match_segments(pattern_segs, path_segs)
