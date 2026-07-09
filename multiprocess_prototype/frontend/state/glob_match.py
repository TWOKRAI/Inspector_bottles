"""glob_match.py — Glob-матчинг путей StateStore для GUI-подписок.

Тонкий нормализующий фасад над ЕДИНЫМ матчером framework
(`state_store_module.core.match_pattern`). Раньше здесь жила дословная копия
алгоритма (`_match_segments`/`_split_dotted`) — «портировано, копируем, не
импортируем». 5.9 убирает дубликат: path×pattern-матчинг теперь в ОДНОМ месте
(framework), GUI лишь нормализует ведущие/завершающие точки и делегирует.

Поддерживаемый синтаксис (задаётся framework-матчером):
  - '*'  — ровно один сегмент пути (любой).
  - '**' — ноль или более сегментов пути (рекурсивно).
  - Литерал — точное совпадение (case-sensitive).
"""

from __future__ import annotations

from multiprocess_framework.modules.state_store_module.core import (
    match_pattern,
    split_pattern,
)


def match_glob(pattern: str, path: str) -> bool:
    """Проверить совпадение glob-паттерна с путём StateStore.

    Ведущие/завершающие точки нормализуются (обрезаются), затем матчинг
    делегируется единому framework-матчеру (`core.match_pattern`) —
    поведение клиента и сервера гарантированно совпадает.

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
    # Нормализация: обрезаем ведущие/завершающие точки (framework-матчер этого
    # не делает — он ожидает уже разбитые сегменты).
    pattern_segs = split_pattern(pattern.strip("."))
    path_segs = split_pattern(path.strip("."))
    return match_pattern(pattern_segs, path_segs)
